import stripe
import os
from flask import Flask, render_template, redirect, url_for, request, jsonify, send_from_directory, session, send_file
from flask_mail import Mail, Message
from config import STRIPE_SECRET_KEY, STRIPE_PRICE_ID, STRIPE_WEBHOOK_SECRET, MAIL_USERNAME, MAIL_PASSWORD
from pyairtable import Table, Api
from pyairtable.formulas import match
from dotenv import load_dotenv
from datetime import datetime
from collections import Counter, defaultdict
from babel.dates import format_date
import pandas as pd
import io
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
load_dotenv()

# locale.setlocale(locale.LC_TIME, 'it_IT.UTF-8') #Non supportato da Koyeb

app = Flask(__name__)
app.secret_key = os.urandom(24)

stripe.api_key = STRIPE_SECRET_KEY
STRIPE_PRICE_ID = STRIPE_PRICE_ID #"price_1RN9mhEF8NjwgIEO4ZGym71S" #reale > "price_1RN9QQEF8NjwgIEOh6LgsLD4"
STRIPE_WEBHOOK_SECRET = STRIPE_WEBHOOK_SECRET #'whsec_b7142045be6eda2db162e890c9acd6ac2d348dfd24f4401b9d334eb8a672e781' #di prova nel locale, scade dopo 90 giorni

AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
api = Api(AIRTABLE_TOKEN)

# Configura Flask-Mail
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = MAIL_USERNAME
app.config['MAIL_PASSWORD'] = MAIL_PASSWORD

mail = Mail(app)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/robots.txt')
def robots():
    return send_from_directory('static', 'robots.txt')

@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('static', 'sitemap.xml')

@app.route('/piani')
def piani():
    return render_template('piani.html')


@app.route('/messaggio_inviato')
def messaggio_inviato():
    return render_template('messaggio_inviato.html')

@app.route('/contact', methods=['POST'])
def contact():
    name = request.form['name']
    telefono = request.form['telefono']
    dipendenti = request.form['dipendenti']
    message = request.form['message']

    msg = Message(subject=f"Nuovo Contatto TeamTime da {name}",
                  sender=app.config['MAIL_USERNAME'],
                  recipients=["help.teamtime@gmail.com"],
                  body=f"""Messaggio da:
                  Azienda: {name}
                  Dipendenti: {dipendenti}
                  Telefono: {telefono}
                  Messaggio: {message}""")
    mail.send(msg)
    return redirect(url_for('messaggio_inviato'))


@app.route('/checkout')
def checkout():
    return render_template('checkout.html')

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price': STRIPE_PRICE_ID,
            'quantity': 1,
        }],
        mode='subscription',
        success_url=url_for('success', _external=True),
        cancel_url=url_for('checkout', _external=True),
    )
    return redirect(session.url, code=303)

@app.route('/success')
def success():
    return render_template('success.html')

@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError as e:
        return jsonify({"error": str(e)}), 400

    # 🔍 Gestione degli eventi
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        customer_email = session.get('customer_email', '[nessuna email]')
        print(f"✅ Pagamento completato da: {customer_email}")
        # Qui puoi aggiornare il tuo DB, inviare email, sbloccare accesso ecc.

    return jsonify({'status': 'success'}), 200


# DASHBOARD

@app.route('/login', methods=['GET', 'POST'])
def login():
    TABLE_NAME = "Locali Approvati"
    table = Table(AIRTABLE_TOKEN, AIRTABLE_BASE_ID, TABLE_NAME)
    if request.method == 'POST':
        email = request.form.get('email-username')
        password = request.form.get('password')
        try:
          data = table.first(formula=match({"Mail": email}))
          user_password = data['fields']['Password']
          print(f"User Password da Airtable: {user_password}")
        except Exception as e:
          print(f"Errore: {e}")
        
        # Logica di autenticazione
        if email == data['fields']['Mail'] and password == user_password:
            print(f"Data Fields {data['fields']}")
            session['data'] = data['fields']
            print(f"Session: {session['data']}")
            return redirect(url_for('dashboard')) 
        else:
            return "Credenziali non valide", 401

    # Se è una richiesta GET → mostra il form
    return render_template('auth-login-basic.html')

@app.route('/dashboard')
def dashboard():
    data = session.get("data")
    print(f"Data da Login: {data}")
    oggi = datetime.now().strftime('%Y-%m-%d')
    mese_corrente = format_date(datetime.now(), format="LLLL", locale='it').lower()
    if not data:
        return redirect(url_for('login'))
    
    TABLE_NAME = data['Locale']
    table = api.table(AIRTABLE_BASE_ID, TABLE_NAME)

    #records = table.all()
    records = table.all(sort=["-Created"])
    #print(f"Records: {records}")
    len_records = len(records)
    oggi_records = [r for r in records if r["fields"].get("Created") == oggi]
    mese_records = [r for r in records if r["fields"].get("Mese Nome") == mese_corrente]
    len_oggi_records = len(oggi_records)
    len_mese_records = len(mese_records)
    ultimi6_records = records[:6]
    #print(ultimi6_records)
    #print(len_mese_records)
    #print(f"Record di Oggi: {oggi_records}")
    #print(f"Record trovati: {len(records)}")
    percentage = round((len_records / data['Max Rows']) * 100)
    #print(f"Percentuale: {percentage}")

    ore = []
    location_counter = defaultdict(int)
    gps_locations = []
    counter_al_lavoro = 0
    counter_ore_lavorate_oggi = 0
    counter_ore_lavorate_mese = 0
    for record in oggi_records:
      entrata = record["fields"].get("Entrata")
      uscita = record["fields"].get("Uscita")
      ore_lavorate_oggi = record["fields"].get("Ore Lavorate")
      if entrata:
        ora = entrata.split(":")[0].zfill(2)  # "9" → "09"
        ore.append(ora)
      if uscita == "Al lavoro":
        counter_al_lavoro += 1
      if "NaN" not in str(ore_lavorate_oggi):
        counter_ore_lavorate_oggi += round(ore_lavorate_oggi, 2)

    for record in mese_records:
       ore_lavorate_mese = record["fields"].get("Ore Lavorate")
       gps = record['fields'].get('GPS', 'Sconosciuto')
       location_counter[gps] += 1
       if "NaN" not in str(ore_lavorate_mese):
        #print(ore_lavorate_mese)
        counter_ore_lavorate_mese += round(ore_lavorate_mese, 2)
       
    counter_ore_lavorate_mese = round(counter_ore_lavorate_mese, 2)
    #print(f"Counter Ore Lavorate Mese: {counter_ore_lavorate_mese}")
    #print(counter_ore_lavorate_oggi)
    try:
       media_ore_mese = round(counter_ore_lavorate_mese / len_mese_records, 2) #counter_ore_lavorate_mese
       print(f"Media Mese Giornaliera: {media_ore_mese}")
    except Exception as e:
       print(f"Errore Media Mese Giornaliera: {e}")
       return "N/A"
    

# Conta quanti ingressi per ogni ora
    grafico_conteggio_ore = Counter(ore)

# Crea una lista ordinata per tutte le 24 ore
    grafico_etichette_ore = [f"{h:02d}" for h in range(24)]
    grafico_valori = [grafico_conteggio_ore.get(ora, 0) for ora in grafico_etichette_ore]

#Grafico GPS
    top_3_locations = Counter(location_counter).most_common(3)
    GPS_labels = [item[0] for item in top_3_locations]
    GPS_series = [item[1] for item in top_3_locations]
    #print(GPS_labels)
    session['monitor_url'] = data.get('Monitor URL')
    session['staff_url'] = data.get('Monitor Ore Mensili')

    return render_template("dashboard.html", data=data, GPS_labels=GPS_labels, GPS_series=GPS_series, ultimi6_records=ultimi6_records, media_ore_mese=media_ore_mese, mese_corrente=mese_corrente, counter_ore_lavorate_oggi=counter_ore_lavorate_oggi, counter_ore_lavorate_mese=counter_ore_lavorate_mese, counter_al_lavoro=counter_al_lavoro, percentage=percentage, len_records=len_records, len_mese_records=len_mese_records, len_oggi_records=len_oggi_records, records=records, oggi_records=oggi_records, grafico_etichette_ore=grafico_etichette_ore,
    grafico_valori=grafico_valori)

@app.route('/calendario')
def calendario():
    data = session.get("data")
    if not data:
        return redirect(url_for('login'))
    monitor_url = data.get('URL Monitor')
    monitor_url = monitor_url.replace("https://airtable.com/", "https://airtable.com/embed/")
    full_url = monitor_url + "?viewControls=on"
    print(full_url)

    return render_template('calendario.html', full_url=full_url)

@app.route('/staff')
def staff():
    data = session.get("data")
    print(data)
    if not data:
        return redirect(url_for('login'))
    staff_url = data.get('Monitor Ore Mensili')
    print(staff_url)
    staff_url = staff_url.replace("https://airtable.com/", "https://airtable.com/embed/")
    full_url = staff_url + "?viewControls=on"
    print(full_url)

    return render_template('staff.html', full_url=full_url)

@app.route('/report', methods=['GET', 'POST'])
def report():
    data = session.get("data")
    records = session.get("records") #**da togliere?

    if not data:
        return redirect(url_for('login'))
    
    TABLE_NAME = data['Locale']
    table = api.table(AIRTABLE_BASE_ID, TABLE_NAME)

    #records = table.all()
    records = table.all(sort=["-Created"])
    # Estrai tutti i mesi unici
    mesi_disponibili = sorted(set(r['fields'].get("Mese Nome", "").lower() for r in records if "Mese Nome" in r['fields']))

    if request.method == 'POST':
        mese_selezionato = request.form.get("mese")
        if not mese_selezionato:
            return "Errore: mese non selezionato", 400

        # Filtra i record per il mese selezionato
        filtered = [r for r in records if r['fields'].get('Mese Nome', '').lower() == mese_selezionato.lower()]

        # Organizza i dati: mappa → nome → giorno → ore
        data_dict = {}
        for r in filtered:
            f = r['fields']
            nome = f.get("Nome", "Sconosciuto")
            giorno = str(f.get("Giorni"))
            ore = f.get("Ore Lavorate", 0)
            if isinstance(ore, dict):  # Gestione di {'specialValue': 'NaN'}
                ore = 0
            
            if nome not in data_dict:
              data_dict[nome] = {}
            if giorno not in data_dict[nome]:
              data_dict[nome][giorno] = 0
            data_dict[nome][giorno] += round(ore, 2)


        # Crea intestazione colonne: 1...31 + mese + anno
        giorni_colonne = [str(i) for i in range(1, 32)]
        header = giorni_colonne + ['Totale', 'Mese', 'Anno']

        # Costruzione righe
        rows = []
        for nome, giorni in data_dict.items():
            giornaliere = [giorni.get(day, 0) for day in giorni_colonne]
            totale = round(sum(giornaliere), 2)
            mese = mese_selezionato
            anno = filtered[0]['fields'].get("Anno", "") if filtered else ""
            rows.append([nome] + giornaliere + [totale, mese, anno])

        # Crea DataFrame
        df = pd.DataFrame(rows, columns=["Nome Cognome"] + header)

        # Genera file Excel in memoria
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name="Report", index=False)
            workbook  = writer.book
            worksheet = writer.sheets["Report"]
            worksheet.set_column(0, 0, 30)  # Colonna 0 = prima colonna, larghezza 30
        output.seek(0)

        return send_file(output, download_name="report.xlsx", as_attachment=True)

    return render_template("report.html", mesi_disponibili=mesi_disponibili)

@app.route('/logout')
def logout():
    session.clear()  # Rimuove tutti i dati salvati nella sessione
    return redirect(url_for('login'))

@app.route('/download-pdf', methods=['POST']) #** da vedere
def download_pdf():
    data = session.get("data")
    if not data:
      return redirect(url_for("login"))

    TABLE_NAME = data['Locale']
    table = api.table(AIRTABLE_BASE_ID, TABLE_NAME)
    records = table.all(sort=["-Created"])

    mese_selezionato = request.form.get("mese")
    if not mese_selezionato:
        return "Errore: mese non selezionato", 400

    # Filtra i dati
    filtered = [r for r in records if r['fields'].get('Mese Nome', '').lower() == mese_selezionato.lower()]

    # Aggrega ore per giorno
    data_dict = {}
    for r in filtered:
        f = r['fields']
        nome = f.get("Nome", "Sconosciuto")
        giorno = str(f.get("Giorni"))
        ore = f.get("Ore Lavorate", 0)
        if isinstance(ore, dict):
            ore = 0
        if nome not in data_dict:
            data_dict[nome] = {}
        if giorno not in data_dict[nome]:
            data_dict[nome][giorno] = 0
        data_dict[nome][giorno] += round(ore, 2)

    giorni_colonne = [str(i) for i in range(1, 32)]

    # Crea il PDF
    output = io.BytesIO()
    p = canvas.Canvas(output, pagesize=A4)
    width, height = A4

    x = 40
    y = height - 40
    p.setFont("Helvetica-Bold", 12)
    p.drawString(x, y, f"Report ore lavorate - Mese: {mese_selezionato.title()}")
    y -= 30

    p.setFont("Helvetica", 10)
    for nome, giorni in data_dict.items():
        riga = f"{nome}:"
        p.drawString(x, y, riga)
        y -= 15

        dettagli = ""
        totale = 0
        for g in giorni_colonne:
            ore = giorni.get(g, 0)
            if ore:
                dettagli += f"{g}:{ore}  "
                totale += ore
        dettagli += f" | Totale: {round(totale, 2)}"
        p.drawString(x + 20, y, dettagli)
        y -= 25
        if y < 50:
            p.showPage()
            y = height - 40

    p.save()
    output.seek(0)

    return send_file(output, download_name="report.pdf", as_attachment=True)

@app.route('/privacy')  
def privacy():
    return render_template("privacy.html")


if __name__ == '__main__':
    app.run(debug=True)

