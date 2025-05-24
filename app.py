import stripe
import locale
import os
from flask import Flask, render_template, redirect, url_for, request, jsonify, send_from_directory, session
from flask_mail import Mail, Message
from config import STRIPE_SECRET_KEY, STRIPE_PRICE_ID, STRIPE_WEBHOOK_SECRET, MAIL_USERNAME, MAIL_PASSWORD
from pyairtable import Table, Api
from pyairtable.formulas import match
from dotenv import load_dotenv
from datetime import datetime
from collections import Counter, defaultdict
from babel.dates import format_date
load_dotenv()

locale.setlocale(locale.LC_TIME, 'it_IT.UTF-8') #Non supportato da Koyeb

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
        except Exception as e:
          print(f"Errore: {e}")
        
        # Logica di autenticazione
        if email == data['fields']['Mail'] and password == user_password:
            session['data'] = data['fields']
            return redirect(url_for('dashboard')) 
        else:
            return "Credenziali non valide", 401

    # Se è una richiesta GET → mostra il form
    return render_template('auth-login-basic.html')

@app.route('/dashboard')
def dashboard():
    data = session.get("data")
    #print(f"Data da Login: {data}")
    oggi = datetime.now().strftime('%Y-%m-%d')
    mese_corrente = format_date(datetime.now(), format="LLLL", locale='it').lower()
    if not data:
        return redirect(url_for('login'))
    
    TABLE_NAME = data['Locale']
    table = api.table(AIRTABLE_BASE_ID, TABLE_NAME)

    #records = table.all()
    records = table.all(sort=["-Created"])
    #print(records)
    len_records = len(records)
    oggi_records = [r for r in records if r["fields"].get("Created") == oggi]
    mese_records = [r for r in records if r["fields"].get("Mese Nome") == mese_corrente]
    len_oggi_records = len(oggi_records)
    len_mese_records = len(mese_records)
    ultimi6_records = records[:6]
    print(ultimi6_records)
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
    print(GPS_labels)

    return render_template("dashboard.html", data=data, GPS_labels=GPS_labels, GPS_series=GPS_series, ultimi6_records=ultimi6_records, media_ore_mese=media_ore_mese, mese_corrente=mese_corrente, counter_ore_lavorate_oggi=counter_ore_lavorate_oggi, counter_ore_lavorate_mese=counter_ore_lavorate_mese, counter_al_lavoro=counter_al_lavoro, percentage=percentage, len_records=len_records, len_mese_records=len_mese_records, len_oggi_records=len_oggi_records, records=records, oggi_records=oggi_records, grafico_etichette_ore=grafico_etichette_ore,
    grafico_valori=grafico_valori)

if __name__ == '__main__':
    app.run(debug=True)

