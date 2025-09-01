import stripe
import os
from flask import Flask, render_template, redirect, url_for, request, jsonify, send_from_directory, session, send_file, abort
from flask_mail import Mail, Message
from config import STRIPE_SECRET_KEY, STRIPE_PRICE_ID, STRIPE_WEBHOOK_SECRET, MAIL_USERNAME, MAIL_PASSWORD
from pyairtable import Table, Api
from pyairtable.formulas import match
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict
from babel.dates import format_date
import pandas as pd
import io
import time
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
import requests
import random, string
import schedule
from openai import OpenAI
import json
import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url #** non usato?
import threading
import xml.etree.ElementTree as ET

load_dotenv()

# locale.setlocale(locale.LC_TIME, 'it_IT.UTF-8') #Non supportato da Koyeb

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") #, "una-chiave-molto-segreta-e-lunga")  # <-- Cambia qui

stripe.api_key = STRIPE_SECRET_KEY
STRIPE_PRICE_ID = STRIPE_PRICE_ID
STRIPE_WEBHOOK_SECRET = STRIPE_WEBHOOK_SECRET
STRIPE_WEBHOOK_SECRET_KOYEB = os.getenv("STRIPE_WEBHOOK_SECRET_KOYEB")
AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
api = Api(AIRTABLE_TOKEN)
TELEGRAM_BOT_KEY = os.getenv("TELEGRAM_BOT_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID")
OPENAI_APIKEY = os.getenv("OPENAI_APIKEY")
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL")
CLOUDINARY_APIKEY = os.getenv("CLOUDINARY_APIKEY")
CLOUDINARY_APISECRET = os.getenv("CLOUDINARY_APISECRET")
CLOUDINARY_CLOUDNAME = os.getenv("CLOUDINARY_CLOUDNAME")


# Configura Flask-Mail
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = MAIL_USERNAME
app.config['MAIL_PASSWORD'] = MAIL_PASSWORD

mail = Mail(app)

def invia_telegram_async(ip, user_agent, referer, page, bot): #messaggio telegram in threading per non appesantire il caricamento della pagina**
    try:
       telegram(f"{bot} - Page: {page}, Home: {ip}, User Agent: {user_agent}, sorgente: {referer}")
    except Exception as e:
       print(f"{e}")

@app.route('/')
def home():
    ip = request.remote_addr
    user_agent = request.headers.get('User-Agent')
    referer = request.headers.get('Referer', 'Diretto')
    telegram(f"Home: {ip}, User Agent: {user_agent}, sorgente: {referer}")
    return render_template('index.html')

@app.route('/robots.txt')
def robots():
    return send_from_directory('static', 'robots.txt')

@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('static', 'sitemap.xml')

@app.route('/piani')
def piani():
    ip = request.remote_addr
    user_agent = request.headers.get('User-Agent')
    path = request.path
    telegram(f"Piani: {ip}, User Agent: {user_agent}, sorgente: {path}")
    return render_template('piani.html')


@app.route('/messaggio_inviato')
def messaggio_inviato():
    return render_template('messaggio_inviato.html')


@app.route('/contact', methods=['POST'])
def contact():
    telegram("Browse: contact")
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
            payload, sig_header, STRIPE_WEBHOOK_SECRET_KOYEB  #forse è da cancellare quell'altra STRIPE_WEBHOOK_SECRET (da tenere per test interni) - dovrò metterne una con koyeb
        )
    except stripe.error.SignatureVerificationError as e:
        print(f"Errore: {e}")
        return jsonify({"error": str(e)}), 400
    
    table = api.table(AIRTABLE_BASE_ID, "Locali Approvati")
    #record = table.first(formula=match({"Stripe Customer ID": customer_id})) Qui non serve perché non ha il dato customer_id non avendo eventi
    
    
    
    if event['type'] == 'checkout.session.completed': #**questo è dal sito carrello?
        session = event['data']['object']
        customer_email = session.get('customer_email', '[nessuna email]')
        print(f"✅ checkout.session.completed → Pagamento iniziale da: {customer_email}")
        #** Azioni: crea record Airtable, invia email, ecc.

    # Pagamento riuscito dopo prova gratuita (o rinnovo)
    elif event['type'] == "customer.subscription.created": #** qui bisogna sviluppare! invio mail di creazione profilo abbonamento/ non serve perché già la riceve dopo
       invoice = event['data']['object']
       customer_id = invoice['customer']
       #record = table.first(formula=match({"Stripe Customer ID": customer_id})) non lo ha ancora, crea dopo il record in airtable!
       print(f"🎉 Creato nuovo abbonamento gratuito per {customer_id}")
       telegram("Nuovo Abbonamento Gratuito Creato")
       
    elif event['type'] == 'invoice.payment_succeeded': # Questo evento si verifica circa un'ora dopo che il customer subscription created o updated. No, questo si crea anche subito al created, si crea un'ora dopo il pagamento
        invoice = event['data']['object']
        customer_id = invoice['customer']
        billing_reason = invoice.get('billing_reason', 'unknown')
        #record = table.first(formula=match({"Stripe Customer ID": customer_id})) Non lo ha ancora! **Da vedere bene
        amount = invoice['amount_paid'] / 100  # converti da cent a €
        if amount == 0:
          print(f"Prova Gratuita Attivata da {customer_id}: {amount}€, billing_reason: {billing_reason}") #, locale: {record['fields']['Locale']}") non lo ha ancora!
        else:
          record = table.first(formula=match({"Stripe Customer ID": customer_id}))
          print(f"💰 Pagamento ricevuto da {customer_id}: {amount}€, billing_reason: {billing_reason}, locale: {record['fields']['Locale']}") #Qui lo dovrebbe avere perché è il pagamento dopo la prova
          telegram("Nuovo Pagamento Ricevuto")
          if record['fields']['Referral'] and record['fields']['Referral'] != "-":
             telegram(f"[REF] Periodo di prova terminato con successo. Riconosciuto reward per referral: {record['fields']['Referral']}")
          try: 
            table.update(record["id"], {"Pagato": 'Si'})
            print(f"Airtable: Aggiornato stato Pagato in 'Si' per: {customer_id}, billing_reason: {billing_reason}, locale: {record['fields']['Locale']}") #, ") 
          except Exception as e:
            print(f"Errore durante l'aggiornamento dello stato 'Pagato in Airtable per {customer_id}: {e}, billing_reason: {billing_reason}, locale: {record['fields']['Locale']}")

    elif event['type'] == 'customer.subscription.updated': # Questi sono i casi in cui l'abbonamento cambia, tipo si rinnova o è disdetto o si attiva dopo il periodo di prova
      subscription = event['data']['object']
      customer_id = subscription['customer']
      record = table.first(formula=match({"Stripe Customer ID": customer_id}))
      previous_attributes = event['data'].get('previous_attributes', {})
    
    # Caso: Disdetta pianificata
      if subscription.get('cancel_at_period_end') and subscription.get('canceled_at'): 
        print(f"❌ Abbonamento disdetto per: {customer_id}, "
      f"Motivo: {subscription['cancellation_details'].get('feedback', 'Nessuno')}, "
      f"Feedback: {subscription['cancellation_details'].get('comment', 'Nessuno')}")
        telegram("Abbonamento disdetto")
        telegram(f"[REF] Abbonamento disdetto per referral: {record['fields']['Referral']}")
        msg = Message(
    subject="Abbonamento Annullato - TeamTime",
    sender=app.config['MAIL_USERNAME'],
    recipients=[record['fields']['Mail']],
    body="""Gentile utente,

abbiamo ricevuto la tua richiesta di annullamento dell’abbonamento a TeamTime – Registro Presenze.

L'accesso verrà automaticamente disattivato.
Per riattivarlo in qualsiasi momento, puoi cliccare qui: https://google.com

Se hai bisogno di supporto o vuoi condividere un feedback sull’esperienza, ti invitiamo a rispondere direttamente a questa email.
Saremo felici di aiutarti o di migliorare grazie ai tuoi suggerimenti!

A presto,
Il Team di TeamTime
""",
    html=f"""<p>Gentile utente,</p>
<p>Abbiamo ricevuto la tua richiesta di annullamento dell’abbonamento a <strong>TeamTime – Registro Presenze</strong>.</p>
<p>L'accesso verrà automaticamente disattivato.<br>
Per riattivarlo in qualsiasi momento, puoi <a href="{record['fields']['Link Annullamento']}">cliccare qui</a>.</p>
<p>Se hai bisogno di supporto o vuoi condividere un feedback sull’esperienza, ti invitiamo a rispondere direttamente a questa email.<br>
Saremo felici di aiutarti o di migliorare grazie ai tuoi suggerimenti!</p>
<p>A presto,<br>Il Team di TeamTime</p>"""
)

        mail.send(msg)

        try: 
          table.update(record["id"], {"Status": 'Disattivato'})
          print(f"❌ Abbonamento aggiornato su Airtable per: {customer_id}")
        except Exception as e:
          print(f"Errore durante disdetta abbonamento in Airtable {e}")


    # Caso: Riattivazione (cancel_at_period_end = False)
      if previous_attributes.get("cancel_at_period_end") == True and subscription.get("cancel_at_period_end") == False:
        print(f"✅ Abbonamento riattivato per: {customer_id}")
        record = table.first(formula=match({"Stripe Customer ID": customer_id}))
        telegram("Abbonamento Riattivato")
        try: 
          table.update(record["id"], {"Status": 'Attivo'})
          print(f"✅ Abbonamento aggiornato su Airtable per: {customer_id}")
          msg = Message(
            subject="Abbonamento Riattivato - TeamTime",
            sender=app.config['MAIL_USERNAME'],
            recipients=[record['fields']['Mail']],
            body=f"""Gentile utente,

il tuo abbonamento a TeamTime – Registro Presenze è stato riattivato con successo.
Tutti i tuoi dati e le funzionalità sono di nuovo pienamente accessibili.

Grazie per aver scelto di continuare con noi!
Per qualsiasi necessità, puoi rispondere direttamente a questa email: siamo sempre disponibili ad aiutarti.

Buon lavoro con TeamTime!
Il Team di TeamTime"""
)
          mail.send(msg)
        except Exception as e:
          print(f"Errore durante rinnovo manuale abbonamento in Airtable {e}")

    # Caso: Finita la prova e abbonamento attivato
      if previous_attributes.get("status") == "trialing" and subscription['status'] == 'active':
        record = table.first(formula=match({"Stripe Customer ID": customer_id}))
        print(f"✅ Attivazione Abbonamento dopo periodo di prova per {customer_id}")
        telegram("Abbonamento attivato dopo periodo di prova")
        table.update(record["id"], {"Status": 'Attivo'})
        msg = Message(
          subject="Benvenuto ufficialmente in TeamTime",
          sender=app.config['MAIL_USERNAME'],
          recipients=[record['fields']['Mail']],
          body=f"""Gentile utente,

il tuo periodo di prova gratuito è terminato e siamo felici di darti il benvenuto ufficiale tra gli abbonati di TeamTime – Registro Presenze!

Per qualsiasi dubbio o necessità, il nostro staff è sempre a tua disposizione.
Puoi rispondere direttamente a questa email.

Grazie per averci scelto,
Il Team di TeamTime"""
)
        mail.send(msg)


      else:
        print(f"🔁 Altra modifica all’abbonamento per: {customer_id}")

    # ❌ Pagamento fallito
    elif event['type'] == 'invoice.payment_failed':
        invoice = event['data']['object']
        customer_id = invoice['customer']
        billing_reason = invoice.get('billing_reason', 'unknown')
        record = table.first(formula=match({"Stripe Customer ID": customer_id}))
        print(f"❌ invoice.payment_failed → Pagamento fallito per {customer_id}, billing_reason: {billing_reason}")
        telegram("Pagamento Fallito")
        try: 
          table.update(record["id"], {"Status": 'Disattivato'})
          print(f"❌ Pagamento non riuscito per: {customer_id}")
          msg = Message(subject=f"Pagamento Fallito - TeamTime",
                  sender=app.config['MAIL_USERNAME'],
                  recipients=[f"{record['fields']['Mail']}", 'help.teamtime@gmail.com'],
                  body=f"""Gentile cliente,

ci risulta che il pagamento previsto al termine dei 30 giorni di prova dell’applicazione TeamTime – Registro Presenze non è andato a buon fine.
Per questo motivo, il suo profilo è stato temporaneamente disattivato.

La invitiamo a contattarci al più presto per ripristinare il servizio e mantenere attivi i suoi privilegi.
Può rispondere direttamente a questa email per ricevere assistenza.

Cordiali saluti,
TeamTime Staff""")
          mail.send(msg)
        except Exception as e:
          print(f"Errore durante il pagamento: {e}")

    return jsonify({'status': 'success'}), 200


# DASHBOARD

@app.route('/login', methods=['GET', 'POST'])
def login():
    TABLE_NAME = "Locali Approvati"
    table = Table(AIRTABLE_TOKEN, AIRTABLE_BASE_ID, TABLE_NAME)
    if request.method == 'POST':
        email = request.form.get('email-username')
        password = request.form.get('password')
        if "@" in email:
            data = table.first(formula=match({"Mail": email}))
        else:
            data = table.first(formula=match({"Locale": email}))
        try:
          user_password = data['fields']['Password']
          #print(f"User Password da Airtable: {user_password}")
        except Exception as e:
          print(f"Errore: {e}")
          telegram(f"Login Errato per {email}")
          return redirect(url_for('login_failed', motivo="Username e Password errate")) 
        
        # Logica di autenticazione
        if data['fields']['Status'] == "Attivo":
            if (email == data['fields']['Mail'] or email == data['fields']['Locale']) and password == user_password:
            #print(f"Data Fields {data['fields']}")
              session['data'] = data['fields']
            #print(f"Session: {session['data']}")
              telegram(f"Login Effettuato: {email}")
              return redirect(url_for('dashboard')) 
            else:
              telegram(f"Login Fallito: {email}")
              return redirect(url_for('login_failed', motivo="Username e Password errate"))
              
        else:
            telegram(f"Login Fallito: Servizio Disattivato")
            return redirect(url_for('login_failed', motivo="Il servizio per questo QR Code è stato disattivato, contatta l'assistenza"))

    # Se è una richiesta GET → mostra il form
    return render_template('auth-login-basic.html')

@app.route('/login-failed')
def login_failed():
    motivo = request.args.get('motivo', 'Username o Password errata')
    TABLE_NAME = "Locali Approvati"
    table = Table(AIRTABLE_TOKEN, AIRTABLE_BASE_ID, TABLE_NAME)
    if request.method == 'POST':
        email = request.form.get('email-username')
        password = request.form.get('password')
        if "@" in email:
            data = table.first(formula=match({"Mail": email}))
        else:
            data = table.first(formula=match({"Locale": email}))
        try:
          data = table.first(formula=match({"Mail": email}))
          user_password = data['fields']['Password']
          print(f"User Password da Airtable: {user_password}")
        except Exception as e:
          print(f"Errore: {e}")
          return redirect(url_for('login_failed', motivo=motivo))
        
        # Logica di autenticazione
        if (email == data['fields']['Mail'] or email == data['fields']['Locale']) and password == user_password:
            print(f"Data Fields {data['fields']}")
            session['data'] = data['fields']
            print(f"Session: {session['data']}")
            return redirect(url_for('dashboard')) 
        else:
            return redirect(url_for('login_failed', motivo=motivo))
    return render_template('auth-login-failed.html', motivo=motivo)

@app.route('/dashboard')
def dashboard():
    data = session.get("data")
    print(f"Data da Login: {data}")
    
    oggi = datetime.now().strftime('%Y-%m-%d')
    mese_corrente = format_date(datetime.now(), format="LLLL", locale='it').lower()
    if not data:
        return redirect(url_for('login'))
    
    telegram(f"Dashboard: {data['Locale']}")
    table = api.table(AIRTABLE_BASE_ID, "Locali Approvati")
    record = table.first(formula=match({"Locale": data['Locale']}))
    status_locale = record["fields"].get("Status", "")

    if status_locale != "Attivo":
        print(f"❌ Accesso negato: status = {status_locale}")
        session.clear()
        return redirect(url_for('login_failed', motivo="Il servizio su questo QR Code è stato disattivato, contattare l'assistenza."))

    
    TABLE_NAME = data['Locale']
    table = api.table(AIRTABLE_BASE_ID, TABLE_NAME)

    records = table.all(sort=["-Created"])
    #print(f"Records: {records}")
    len_records = len(records)
    oggi_records = [r for r in records if r["fields"].get("Created") == oggi]
    mese_records = [r for r in records if r["fields"].get("Mese Nome") == mese_corrente]
    len_oggi_records = len(oggi_records)
    len_mese_records = len(mese_records)
    ultimi6_records = records[:6]
    percentage = round((len_records / data['Max Rows']) * 100)

    ore = []
    location_counter = defaultdict(int)
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
        counter_ore_lavorate_mese += round(ore_lavorate_mese, 2)
       
    counter_ore_lavorate_mese = round(counter_ore_lavorate_mese, 2)
    try:
       if len_mese_records:
        media_ore_mese = round(counter_ore_lavorate_mese / len_mese_records, 2)
       else:
        media_ore_mese = 0
    except Exception as e:
       print(f"Errore Media Mese Giornaliera: {e}")
       return """
    Errore nel ricevere le informazioni.<br>
    Svuota la cache del browser o contatta l’assistenza a <a href='mailto:help.teamtime@gmail.com'>help.teamtime@gmail.com</a>.<br>
    <a href='https://www.teamtimeapp.it/login'>🔁 Riprova il login</a>
    """, 200, {'Content-Type': 'text/html'}
    
    TABLE_NAME = "Locali Approvati"
    table = api.table(AIRTABLE_BASE_ID, TABLE_NAME)
    #print(data)
    record = table.first(formula=match({"Locale": data['Locale']}))
    if len_records > 2: #riferito alla tavola di data non di Locali Approvati!
       try:
        table.update(record["id"], {"Primo Accesso": "no"})
       except Exception as e:
        print(f"Errore aggiornando# la casella 'Primo Accesso' sul database:{e}")
    else:
       try:
        table.update(record["id"], {"Primo Accesso": "yes"})
       except Exception as e:
        print(f"Errore aggiornando la casella 'Primo Accesso' sul database:{e}")
       
    

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

@app.route('/primi_passi')
def primi_passi():
    ip = request.remote_addr
    user_agent = request.headers.get('User-Agent')
    path = request.path
    telegram(f"Primi Passi: {ip}, User Agent: {user_agent}, sorgente: {path}")
    data = session.get("data")
    print(f"Data da Login: {data}")
    
    if not data:
        return redirect(url_for('login'))
    
    return render_template('primi_passi.html', data=data)

@app.route('/calendario')
def calendario():
    data = session.get("data")
    if not data:
        return redirect(url_for('login'))
    telegram(f"Calendario: {data['Locale']}")
    monitor_url = data.get('URL Monitor')
    monitor_url = monitor_url.replace("https://airtable.com/", "https://airtable.com/embed/")
    full_url = monitor_url + "?viewControls=on"
    print(full_url)

    return render_template('calendario.html', full_url=full_url, data=data)

@app.route('/staff')
def staff():
    data = session.get("data")
    #print(data)
    if not data:
        return redirect(url_for('login'))
    telegram(f"Staff: {data['Locale']}")
    staff_url = data.get('Monitor Ore Mensili')
    print(staff_url)
    staff_url = staff_url.replace("https://airtable.com/", "https://airtable.com/embed/")
    full_url = staff_url + "?viewControls=on"
    print(full_url)

    return render_template('staff.html', full_url=full_url, data=data)

@app.route('/report', methods=['GET', 'POST']) #Se qualcosa non funziona, ripristinare def report_old poco più sotto
def report():
    data = session.get("data")
    records = session.get("records") #**da togliere?

    if not data:
        return redirect(url_for('login'))
    telegram(f"Report: {data['Locale']}")

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
        #print(filtered)

        forza_generazione = request.form.get("forza_generazione") == "1"
        check_dipendenti_lavoro = any(r['fields'].get("Uscita", "").strip().lower() == "al lavoro" for r in filtered)
        if check_dipendenti_lavoro and not forza_generazione:
          return render_template("report.html", mesi_disponibili=mesi_disponibili, show_popup=True, mese_preselezionato=mese_selezionato, data=data)


        # Organizza i dati: mappa → nome → giorno → ore
        data_dict = {}
        for r in filtered:
            f = r['fields']
            nome = f.get("Nome", "Sconosciuto")
            giorno = f"{int(f.get('Giorni')):02d}" #** qui funziona solo con teamtime022 no giorno = str(f.get("Giorni"))
            ore = f.get("Ore Lavorate", 0)
            if isinstance(ore, dict):  # Gestione di {'specialValue': 'NaN'}
                ore = 0
            
            if nome not in data_dict:
              data_dict[nome] = {}
            if giorno not in data_dict[nome]:
              data_dict[nome][giorno] = 0
            data_dict[nome][giorno] += round(ore, 2)


        # Crea intestazione colonne: 1...31 + mese + anno
        giorni_colonne = [f"{i:02d}" for i in range(1, 32)] #funziona sempre solo con  teamtime022 no, giorni_colonne = [str(i) for i in range(1, 32)]
        header = giorni_colonne + ['Totale', 'Mese', 'Anno']

        # Costruzione righe
        rows = []
        for nome, giorni in data_dict.items():
            giornaliere = [giorni.get(day, 0) for day in giorni_colonne]
            mese = mese_selezionato
            anno = filtered[0]['fields'].get("Anno", "") if filtered else ""
            rows.append([nome] + giornaliere + ["=SUM(B{0}:AF{0})".format(len(rows)+2), mese, anno])

        # Crea DataFrame
        df = pd.DataFrame(rows, columns=["Nome Cognome"] + header)

        # Genera file Excel in memoria
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name="Report", index=False)
            workbook  = writer.book
            worksheet = writer.sheets["Report"]
            worksheet.set_column(0, 0, 30)  # Colonna 0 = prima colonna, larghezza 30
            last_row = len(df) + 2
            worksheet.write(f"A{last_row + 2}", "Report generato automaticamente")
            worksheet.write_url(f"A{last_row + 3}", "https://teamtimeapp.it", string="TeamTime App - Registro Presenze", cell_format=workbook.add_format({'font_color': 'blue', 'underline':  1}))
        output.seek(0)
        msg = Message(subject=f"[TeamTimeWeb Report] {data['Locale']}, {mese_selezionato}",
                  sender=app.config['MAIL_USERNAME'],
                  recipients=["help.teamtime@gmail.com"],
                  body=f"""Richiesto Report Excel Mensile:
                  Locale: {data['Locale']}
                  Mese: {mese_selezionato}""")
        mail.send(msg)

        return send_file(output, download_name=f"{data['Locale']}_{mese_selezionato}_{anno}_report.xlsx", as_attachment=True)

    return render_template("report.html", mesi_disponibili=mesi_disponibili, data=data)


@app.route('/logout')
def logout():
    session.clear()  # Rimuove tutti i dati salvati nella sessione
    return redirect(url_for('login'))


@app.route('/privacy')  
def privacy():
    return render_template("privacy.html")

@app.route('/dashboard_demo')
def dashboard_demo():
    ip = request.remote_addr
    user_agent = request.headers.get('User-Agent')
    path = request.path
    telegram(f"DEMO Dashboard: {ip}, User Agent: {user_agent}, sorgente: {path}")
    return render_template('dashboard_demo.html')

@app.route('/calendario_demo')
def calendario_demo():
    ip = request.remote_addr
    user_agent = request.headers.get('User-Agent')
    path = request.path
    telegram(f"DEMO Calendario: {ip}, User Agent: {user_agent}, sorgente: {path}")
    return render_template('calendario_demo.html')

@app.route('/report_demo')
def report_demo():
    ip = request.remote_addr
    user_agent = request.headers.get('User-Agent')
    path = request.path
    telegram(f"DEMO Report: {ip}, User Agent: {user_agent}, sorgente: {path}")
    return render_template('/report_demo.html')

@app.route('/inizia-prova')
def inizia_prova():
    STRIPE_PUBLIC_KEY = os.getenv('STRIPE_PUBLIC_KEY')
    ip = request.remote_addr
    user_agent = request.headers.get('User-Agent')
    path = request.path
    telegram(f"Inizia-Prova: {ip}, User Agent: {user_agent}, sorgente: {path}")
    ref = request.args.get('ref')  # cerca il ref nella query

    if ref:
        session['ref'] = ref  # salva in sessione
        telegram(f"[REF] Nuovo click per: {ref}")
    else:
        ref = session.get('ref')  # recupera dalla sessione se non presente nella query
        if ref:
            telegram(f"[REF] Nuovo click (sessione) per: {ref}")
        else:
            print("Nessun referral trovato")
    return render_template('/inizia-prova-gratuita.html', STRIPE_PUBLIC_KEY=STRIPE_PUBLIC_KEY)


@app.route('/create-subscription', methods=['POST'])
def create_subscription():
    try:
        data = request.json
        email = data['email']
        payment_method_id = data['payment_method']
        
        piano = data.get('piano', 'START').upper()
        print(f"Piano Scelto {piano}")
        price_lookup = {
            "START": os.environ.get('STRIPE_PRICE_START'),
            "TEAMS": os.environ.get('STRIPE_PRICE_TEAMS'),
            "BUSINESS": os.environ.get('STRIPE_PRICE_BUSINESS'),
        }
        price_id = price_lookup.get(piano, os.environ.get('STRIPE_PRICE_START'))
        items = [{'price': price_id}]

        if data.get('gps') == 'yes':
            items.append({'price': os.environ.get('STRIPE_PRICE_GPS')})
        if data.get('interscambio') == 'yes':
            items.append({'price': os.environ.get('STRIPE_PRICE_INTERSCAMBIO')})

        customer = stripe.Customer.create(
            email=email,
            payment_method=payment_method_id,
            invoice_settings={'default_payment_method': payment_method_id},
        )

        try:
            subscription = stripe.Subscription.create(
                customer=customer.id,
                items=items,
                expand=['latest_invoice.payment_intent'],
                trial_period_days=30
            )
            print(f"✅ Subscription Stripe {subscription.id}")
            payment_intent = subscription.latest_invoice.get('payment_intent')
            
            # ✅ STOP se pagamento fallisce
            if payment_intent and payment_intent['status'] != 'succeeded':
              errore = f"Pagamento rifiutato: {payment_intent['status']}"
              print(f"❌ {errore}")
              return jsonify({"success": False, "error": errore}), 402

            else:
               return jsonify({
              'subscriptionId': subscription.id,
              'clientSecret': payment_intent['client_secret'] if payment_intent else None,
              'customerId': customer.id
            })
        
        except Exception as e:
            errore = str(e)
            print(f"Errore durante la creazione della sottoscrizione: {errore}")
            msg = Message(
                subject="❌ Errore TeamTime - Stripe",
                sender=app.config['MAIL_USERNAME'],
                recipients=["help.teamtime@gmail.com"],
                body=f"Errore durante la creazione della sottoscrizione:\n\n{errore}"
            )
            mail.send(msg)
            return jsonify({"success": False, "error": errore}), 500

    except Exception as e:
        errore = str(e)
        print(f"Errore generale: {errore}")
        return jsonify({"success": False, "error": errore}), 500

def create_subscription_old(): #**backup - errore che se la carta era scaduta continuava comunque a dare accesso
    #print(f"✅ Chiave Stripe in uso: {stripe.api_key}")
    try:
        data = request.json
        email = data['email']
        payment_method_id = data['payment_method']
        

        piano = data.get('piano', 'START').upper()
        print(f"Piano Scelto {piano}")
        price_lookup = {
          "START": os.environ.get('STRIPE_PRICE_START'),
          "TEAMS": os.environ.get('STRIPE_PRICE_TEAMS'),
          "BUSINESS": os.environ.get('STRIPE_PRICE_BUSINESS'),
}
        price_id = price_lookup.get(piano, os.environ.get('STRIPE_PRICE_START')) #"price_1RaCHuEF8NjwgIEOlnXSVo8k" 
        items = [{'price': price_id}]

        if data.get('gps') == 'yes':
          items.append({'price': os.environ.get('STRIPE_PRICE_GPS')})

        if data.get('interscambio') == 'yes':
          items.append({'price': os.environ.get('STRIPE_PRICE_INTERSCAMBIO')})

        # Crea il cliente
        customer = stripe.Customer.create(
            email=email,
            payment_method=payment_method_id,
            invoice_settings={'default_payment_method': payment_method_id},
        )
        #print(f"Customer Stripe {customer}")

        # Crea la sottoscrizione
        #print("Cerco Subscription")
        #print(f"Price ID selezionato: {price_id}")
        #print(f"Items: {items}")
        #trial_end_timestamp = int(time.time()) + 60  # Ora + 60 secondi . Questo va cancellato poi in produzione

        try:
            subscription = stripe.Subscription.create(
              customer=customer.id,
              items=items,
              expand=['latest_invoice.payment_intent'],
              #trial_end=trial_end_timestamp, #da cancellare in produzione
              trial_period_days=30
        )
            print("Tutto ok")
        except Exception as e:
            print(e)
        print(f"Subscription Stripe {subscription}")

        payment_intent = getattr(subscription.latest_invoice, 'payment_intent', None)
        print(f"Payment Intent: {payment_intent}")

        return jsonify({
            'subscriptionId': subscription.id,
            'clientSecret': payment_intent.client_secret if payment_intent else None,
            'customerId': customer.id
        })

    except Exception as e:
        errore = str(e)
        print(f"Errore durante la creazione della sottoscrizione: {errore}")
        msg = Message(
            subject="❌ Errore TeamTime - Stripe",
            sender=app.config['MAIL_USERNAME'],
            recipients=["help.teamtime@gmail.com"],
            body=f"Errore durante la creazione della sottoscrizione:\n\n{errore}"
        )
        mail.send(msg)
        return jsonify({"success": False, "error": errore}), 500


@app.route('/start-airtable', methods=['POST'])
def start_airtable():
    ref = session.get('ref', '-')
    data_json = request.get_json()
    email_cliente = data_json.get('email_cliente', 'nessuna@email.it')
    telefono_cliente = data_json.get('telefono_cliente', 'Nessun Telefono')
    gps_cliente = data_json.get('gps_cliente', 'No GPS')
    interscambio_cliente = data_json.get('interscambio_cliente', 'No Interscambio')
    dipendenti_cliente = data_json.get('numeroDipendenti', 'No Dipendenti Cliente')
    partitaiva_cliente = data_json.get('partitaiva_cliente', 'No vatNumber')
    ragionesociale_cliente = data_json.get('ragionesociale_cliente', 'No companyName')
    indirizzo_cliente = data_json.get('indirizzo_cliente', 'No companyAddress')
    customer_id = data_json.get('customer_id', 'Nessun ID Stripe')

    print("🔁 Inizio ricerca tabella vuota...")
    for i in range(21, 51):  # da teamtime020 a teamtime050 inclusi
        table_name = f"teamtime0{i:02d}"
        print(f"🔍 Controllo tabella: {table_name}")

        try:
            table = api.table(AIRTABLE_BASE_ID, table_name)
            records = table.all()

            if len(records) == 0:
                print(f"✅ OK: {table_name} è vuota")
                table_scelta = table_name
                break  # Ferma appena trovi una tabella vuota

        except Exception as e:
            print(f"❌ Errore , Nessuna tabella disposnibile per {table_name}: {str(e)}")
            msg = Message(subject=f"Errore TeamTime",
                  sender=app.config['MAIL_USERNAME'],
                  recipients=["help.teamtime@gmail.com"],
                  body=f"""Non sono più presenti table disponibili, ricontattare {telefono_cliente}, {ragionesociale_cliente}, customer id: {customer_id}""")
            mail.send(msg)
            break  # Stop se la tabella non esiste

    ora_attuale = datetime.now().strftime('%H:%M')
    table = api.table(AIRTABLE_BASE_ID, table_scelta)
    table.create({
        "Nome": "Attivazione TeamTime",
        "Entrata": ora_attuale,
        "Uscita": ora_attuale,
        "Device": "Computer",
        "GPS": "Privato",
        "GPS Uscita": "Privato"
    })
    print(f"✅ Primo Record Creato in {table_scelta} alle {ora_attuale}")

    nuova_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    fine_prova = datetime.today() + timedelta(days=30)
    #print(fine_prova)

    table = api.table(AIRTABLE_BASE_ID, "Locali Approvati")
    record = table.first(formula=match({"Locale": table_name}))
    file_url = record['fields']['QR Code PDF'][0]['url']
    #print(f"Record {record}")
    #print(f"File url: {file_url}")
    #session['data'] = record['fields']
    #print(f"Prova Data Record: {record['fields']}")
    
     
    if record:
      table.update(record["id"], {"Mail": f'{email_cliente}', "Password": f"{nuova_password}", "Nome": f"{table_scelta}", "Primo Accesso": "yes", "Telefono": f'{telefono_cliente}', "GPS": f"{gps_cliente}", "Intercambio": f"{interscambio_cliente}", "Max Dipendenti": f"{dipendenti_cliente}", "Ragione Sociale": f"{ragionesociale_cliente}", "Partita IVA": f"{partitaiva_cliente}", "Indirizzo": f"{indirizzo_cliente}", "Stripe Customer ID": f"{customer_id}", "Link Annullamento": f"https://www.teamtimeapp.it/termina-abbonamento/{customer_id}", "Fine Prova": f"{fine_prova}", "Status": "Attivo", "Pagato": "No", "Referral": f"{ref}"})
      print(f"✅ Record aggiornato: {table_name} → Mail ={email_cliente}")
      if ref != "-":
        telegram(f"[REF] Nuova Prova Gratuita di 30 Giorni Iniziata per referral: {ref}")
    else:
      print(f"❌ Nessun record trovato per Locale: {table_name} in Locali Approvati")

    
    table = api.table(AIRTABLE_BASE_ID, "SendWebLogin")
    table.create({"Mail": f'{email_cliente}', "Password": f'{nuova_password}', "Telefono": f'{telefono_cliente}', "Max Dipendenti": f"{dipendenti_cliente}", "GPS": f"{gps_cliente}", "Interscambio": f"{interscambio_cliente}", "Fine Prova": f"{fine_prova}", "Locale": f"{table_scelta}", "Attachment": [{"url": file_url}]})

    table = api.table(AIRTABLE_BASE_ID, "MailReminder")
    table.create({"Mail": f'{email_cliente}', "Inviata": "no", "Locale": f"{table_scelta}", "Stripe Customer ID": f"{customer_id}", "Link Annullamento": f"https://www.teamtimeapp.it/termina-abbonamento/{customer_id}"})

    return jsonify({"success": True})

@app.route('/termina-abbonamento/<customer_id>')
def genera_link_disdetta(customer_id):
    telegram("Browse: termina abbonamento")
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url="https://teamtimeapp.it/"  # ← oppure una tua pagina di conferma
    )
    return redirect(session.url)


@app.route('/correggi_orari')
def dipendenti_al_lavoro():
    data = session.get("data")

    if not data:
        return redirect(url_for('login'))
    telegram(f"Correggi Orari: {data['Locale']}")
    
    TABLE_NAME = data['Locale']
    table = api.table(AIRTABLE_BASE_ID, TABLE_NAME)

    records = table.all(sort=["-Created"])

    dipendenti_a_lavoro = []
    for r in records:
        fields = r.get("fields", {})
        if fields.get("Uscita", "").strip().lower() == "al lavoro":
            dipendenti_a_lavoro.append({
                "nome": fields.get("Nome", "Sconosciuto"),
                "entrata": fields.get("Entrata", "—"),
                "created": r.get("createdTime", "—"),
                "gps": fields.get("GPS", "—"),
                "record_id": r.get("id")
            })

    return render_template("correggi_orari.html", dipendenti_a_lavoro=dipendenti_a_lavoro, data=data)


@app.route('/correggi_uscita', methods=['POST'])
def correggi_uscita():
    data = request.get_json()
    record_id = data.get('record_id')
    uscita = data.get('uscita')

    if not record_id or not uscita:
        return "Dati mancanti", 400

    session_data = session.get("data")
    if not session_data:
        return "Non autorizzato", 403

    TABLE_NAME = session_data['Locale']
    table = api.table(AIRTABLE_BASE_ID, TABLE_NAME)

    try:
        table.update(record_id, {"Uscita": uscita})
        return "✅ Modifica salvata, attendi l'aggiornamento della pagina", 200
    except Exception as e:
        return f"Errore: {e}", 500

from flask import render_template

@app.route('/blog')
@app.route('/blog/')
def blog_index():
    ip = request.remote_addr
    user_agent = request.headers.get('User-Agent')
    referer = request.headers.get('Referer', 'Diretto')
    page = "📖 Blog Home"
    if user_agent and "bot" in user_agent.lower():
      bot = "🤖"
    else:
      bot = "🧔🏻"
    threading.Thread(target=invia_telegram_async, args=(ip, user_agent, referer, page, bot)).start()
       
    table = api.table(AIRTABLE_BASE_ID, "Blog")
    categoria = request.args.get("categoria", "Tutte")

    if categoria == "Tutte":
      formula = "{Published} = 1"
    else:
      formula = f"AND({{Published}} = 1, {{Categoria}} = '{categoria}')"

    records = table.all(
      formula=formula,
      sort=["-Created"]
    )

    def map_record(record):
        field = record.get("fields", {})
        data_pubblicazione = field.get("Data") or (record.get("createdTime", "")[:10])
        return {
            "title":   field.get("TitoloCorto"),
            "slug":    field.get("Slug"),
            "image":   field.get("Immagine") or field.get("OgImage"),
            "category":field.get("Categoria") or "Senza Categoria",
            "author":  field.get("Autore") or "Redazione",
            "date":    data_pubblicazione, #** qui si può togliere?
            "excerpt": field.get("Excerpt") or field.get("DescrizioneCorta") or "",
            "reads":   field.get("Letture") or 0,
        }

    articoli = [map_record(r) for r in records]
    return render_template('blog/blogindex.html', articoli=articoli)

@app.route('/blog/<slug>')
@app.route('/blog/<slug>/')
def blog_post(slug):

    ip = request.remote_addr
    user_agent = request.headers.get('User-Agent')
    referer = request.headers.get('Referer', 'Diretto')
    page = "📖" + f"{slug}"
    if user_agent and "bot" in user_agent.lower():
      bot = "🤖"
    else:
      bot = "🧔🏻"
    threading.Thread(target=invia_telegram_async, args=(ip, user_agent, referer, page, bot)).start()

    table = api.table(AIRTABLE_BASE_ID, "Blog")

    safe_slug = (slug or "").replace("'", "\\'")
    formula = f"AND({{Published}} = 1, LOWER({{Slug}}) = '{safe_slug.lower()}')"
    records = table.all(formula=formula, max_records=1)
    #print(records)
    if not records:
        abort(404)
    record = records[0]
    field = record.get("fields", {})
    immagine = field.get("Immagine") or field.get("OgImage")
    toc_items = [line.strip() for line in (field.get("TOC") or "").split("\n") if line.strip()]

    articolo = {
        "title":   field.get("TitoloCorto") or field.get("TitoloLungo") or "Senza titolo",
        "slug":    field.get("Slug") or record.get("id"),
        "cover":   immagine,
        "og_image": field.get("OgImage"),
        "author":  field.get("Autore") or "Redazione",
        "authorbio": field.get("AutoreBio"),
        "date":    field.get("Data") or (record.get("createdTime", "")[:10]),
        "category":field.get("Categoria") or "Senza categoria",
        "excerpt": field.get("Excerpt") or field.get("DescrizioneCorta") or "",
        "meta_description": field.get("MetaDescrizione") or field.get("DescrizioneCorta") or "",
        "reads":   field.get("Letture") or 0,
        "toc":     toc_items,
        "blocks":  [field.get("Blocco1") or "", field.get("Blocco2") or "", field.get("Blocco3") or ""],
        "keywords": field.get("Keyword") or "",
        "introduction": field.get("Introduzione"),
        "faq": field.get("DomandeRisposte") or ""
    }

    if bot == "🧔🏻":
       table.update(record.get("id"), {"Letture": field.get("Letture") + 1})

    return render_template("blog/post.html", articolo=articolo)   

def aggiungi_slug_sitemap(slug, sitemap_path="static/sitemap.xml"):
    print("Caricando la sitemap.xml..")
    # Carica l'albero XML esistente
    tree = ET.parse(sitemap_path)
    root = tree.getroot()

    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    ET.register_namespace('', namespace)

    # Costruisci il link completo
    print("Inserendo il nuovo slug nella sitemap..")
    slug_url = f"https://www.teamtimeapp.it/blog/{slug.lstrip('/')}"

    # Verifica se lo slug è già presente nella sitemap
    for url in root.findall("{%s}url" % namespace):
        loc = url.find("{%s}loc" % namespace)
        if loc is not None and loc.text == slug_url:
            print("Slug già presente nella sitemap.")
            return  # Non aggiunge nulla se è già presente

    # Crea il nuovo tag <url>
    new_url = ET.Element("url")

    loc_tag = ET.SubElement(new_url, "loc")
    loc_tag.text = slug_url

    lastmod_tag = ET.SubElement(new_url, "lastmod")
    lastmod_tag.text = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    ET.SubElement(new_url, "priority").text = "0.80"

    root.append(new_url)
    print("Aggiornando la sitemap.xml..")

    # Funzione ricorsiva per indentare correttamente
    def indent(elem, level=0):
        i = "\n" + level * "  "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = i + "  "
            for child in elem:
                indent(child, level + 1)
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i

    indent(root)
    tree.write(sitemap_path, encoding="utf-8", xml_declaration=True)



def AI_crea_blog_post(argomento, keyword, context_name, link):
    print("Preparazione AI in corso..")
    client = OpenAI(api_key=OPENAI_APIKEY)

    def AI_crea_immagine():
       print("Preparazione AI in corso, 5 secondi di intervallo per darti tempo di disattivarla se non necessario..")
       time.sleep(6)
       print("Creazione prompt per realizzazione immagine AI..") 
       
       system_prompt = f"crea un prompt per dall-e in base a questo argomento: {argomento}, è un'immagine di un post blog, stile realistico semplice, no scritte né numeri nell'immagine"
       message = [
        {"role": "system", "content": system_prompt},
        ]

       print("Generazione risposta per dall-e..")
       resp = client.chat.completions.create(
        model="gpt-4o",
        messages=message,
        temperature=0.8,
    )

       reply = resp.choices[0].message.content
       print(f"Prompt per dall-e ottenuto: {reply}")
       
       
       
       print("Creazione immagine AI in corso..")
       immagine_AI = client.images.generate(
         model="dall-e-3",
         prompt=f"{reply}",# #f"Realistico semplice, assolutamente nessuna scritta né numeri di nessun tipo solo immagini semplici, relativo a: {argomento}. Semplifica al massimo no scritte né numeri",
         n=1,
         size="1024x1024",
         quality="standard"
        )

       # CLODUINARY Configuration       
       cloudinary.config( 
         cloud_name = CLOUDINARY_CLOUDNAME, 
         api_key = CLOUDINARY_APIKEY, 
         api_secret = CLOUDINARY_APISECRET,
         secure=True
         )
       
       try:
          print("Upload immagine su Cloudinary in corso..")
          upload_result = cloudinary.uploader.upload(f"{immagine_AI.data[0].url}", public_id="TeamTime_App_Registro_Presenze_Dipendenti_SoftwareBlog" + str(random.randint(0, 999999)).zfill(6))
          #print(upload_result["secure_url"])
          try:
            immagine_AI_URL = upload_result["secure_url"]
          except Exception as e:
            immagine_AI_URL = "https://i.postimg.cc/mgPsrgX4/image-H-Pt-Zq-Ab-I5q-LFst-JEJL9.webp"
            print(f"Errore caricamento immagine blog: {e}")
       except Exception as e:
          print(f"Error caricamento foto blog su Cloudinary: {e}")
          immagine_AI_URL = "https://i.postimg.cc/mgPsrgX4/image-H-Pt-Zq-Ab-I5q-LFst-JEJL9.webp"

       #immagine_AI_URL = immagine_AI.data[0].url
       
       return immagine_AI_URL
    
    image_url = AI_crea_immagine() #immagine_AI_URL #"https://i.postimg.cc/mgPsrgX4/image-H-Pt-Zq-Ab-I5q-LFst-JEJL9.webp" #
       

    print("Analisi contesto..")
    if context_name == "TeamTime":
       context = """
TeamTime è un un'app gestionale disponibile sia per Apple e Android negli store gratutitamente, sia tramite sito online, che semplifica la gestione entrate/uscite dei dipendenti.
Ha anche una dashboard accessibile via pc dove si può vedere calendario e dettagli dello staff in entrata ed in uscita, unito a utili statistische come la media di ore mensili, settimanali, ore lavorate per ogni dipendente e molto altro.
Obiettivo: conteggio automatico delle ore lavorate, eliminazione delle procedure manuali, risparmio di tempo e maggiore precisione, incluso una reportistica automatica sulle ore del personale per i commercialisti.
PRO: nessun badge fisico, tutto digitalizzato, si può vedere realtime le entrate e le uscite da mobile e da pc, excel precisi, implementazione da un giorno all'altro, prova gratuita di 30 giorni
Funzionamento:
	1. Registrazione azienda e dipendenti → generazione QR code univoco.
	2. Scansione del QR code all entrata e uscita, con possibilità di attivare la geolocalizzazione
	3. Supervisione → visualizzazione orari, dispositivi da app o PC autorizzato.
	4. Risparmio → report mensili con totale ore e confronti tra mesi.
	5. Report Automatici per il commercialista, l'app genera con un click dei report in base alle presenze registrate dai dipendenti
Accesso protetto con username e password.
Report sia aziendale che per singolo dipendente.
Inizia gratis per 30 giorni poi ci sono i piani annuali start, teams e business. Disdici quando vuoi, nessuna penale.
Possibilità di correggere gli orari qualora un dipendente si sia dimenticato di registrare l'uscita
Possibilità Intercambio per poter fare in modo che il dipendente possa registrarsi a più QR Code (per esempio nei cantieri)
"""
    else:
       context = context_name

    print("Analisi prompt..")
    system_prompt = (f"""
    Creami un contenuto JSON per un blog basandoti su questo argomento: {argomento} seguendo tutto SEO Friendly con le {keyword}.Implementando tutti i link utilizzando HTML e non markdown: {link}
    Stile umano, relativamente informale, sei un esperto di software e il tuo obiettivo è consigliare il meglio alle aziende. Dai del tu. Non deve sembrare una pubblicità, specialmente nel Blocco3 sii sincero e consiglia piuttosto che sembrare che stai vendendo. Inoltre tu sei un punto di vista esterno, qualsiasi cosa che ubblicizzi non è di tua proprietà, tu stai esprimendo un giudizio genuino.
    Il testo deve essere diviso per argomenti in blocco1, blocco2 e blocco3 (di cui poi gli indici e titoli vanno nel TOC). La somma di blocco1, blocco2 e blocco3 deve essere tra 600 e 800 parole. Il tutto SEO Friendly con le keyword ({keyword}) utilizzate in maniera naturale, non forzate.
    Il JSON segue questo schema:
    - TitoloCorto : Un testo virale, menzionando inprenscidibilmente la prima tra queste keyword: '{keyword}'
    - DescrizioneCorta : Crea una descrizione di circa 30 parole attinente all'argomento e menzionando almeno una keyword: '{keyword}' in modo naturale
    - Slug : in linea con la prima keyword: '{keyword}, divise da un trattino - e tutto in minuscolo senza spazi, aggiungi anche un numero random da 0 a 100000 con zfill 6. Esempio: le-keywords-328382
    - Introduzione : Una breve introduzione dell'argomento menzionando almeno una tra '{keyword}', almeno 70 parole (non va nel TOC), questo è lo stile "Negli ultimi anni il ruolo degli specialisti HR è profondamente cambiato grazie alla digitalizzazione. Oggi la gestione delle risorse umane è più efficace, veloce e precisa grazie a strumenti digitali avanzati. Scegliere le giuste piattaforme fa la differenza tra un lavoro caotico e uno fluido, ben organizzato ed efficace. (a capo) Vediamo insieme quali sono gli strumenti digitali essenziali per chi opera nelle risorse umane, come sceglierli e perché integrarli nelle attività quotidiane."
    - Autore : Redazione, 
    - AutoreBio: Siamo un team di esperti in software aziendali, con anni di esperienza nel testare, valutare e consigliare le soluzioni più efficaci per imprese di ogni dimensione. Professionali nella ricerca e nella valutazione, ma sempre con un tocco di simpatia! Ogni articolo nasce dalla nostra passione per l’innovazione e dalla voglia di condividere consigli pratici, chiari e utili.
Il nostro obiettivo? Fornire contenuti di valore, scritti con cura, che guidino le aziende verso le scelte software più adatte, senza rinunciare a un sorriso lungo la strada.
    - Immagine : {image_url}
    - Categoria : (Scegli tra Software, Mobile App, Offerte o News in base al contesto)
    - Letture: 0,
    - Blocco1 : testo (senza la scritta Blocco1) almeno 150 parole, qui si affronta il perché della situazione, aggiungi all'inizio una frase del tipo "Come sai in questo blog ci interessiamo di tecnologia per le aziende" o un modo per presentare il blog e definirsi come esperti del settore. Aggiungi anche l'obiettivo del blog, in maniera naturale: analizzare e consigliare i migliori tool e strumenti digitali per ottimizzare o migliorare i processi aziendali. Menziona in modo naturale almeno una di queste keyword: {keyword} e utilizza <strong> per sottolineare un concetto chiave.
    - Blocco2: testo (senza la scritta Blocco2) almeno 150 parole, qui si affronta lo sviluppo della situazione, menziona almeno una keyword: '{keyword}' e utilizza <strong> per sottolineare un concetto chiave
    - Blocco3 : testo (senza la scritta Blocco3), qui inserirai la soluzione di almeno 200 parole, descrivi in maniera naturale il contesto (lo trovi nel contesto qui: '{context}') altrimenti una tua conclusione. Aggiungi i link se presenti: '{link}' in HTML non markdown sottolineati e con colore blu, tipico formato dell'ipertestuale, simile a questo esempio: <a href='http://www.teamtimeapp.it' target="_blank" style='color:blue; text-decoration:underline;'>TESTO</a>
    - Keyword : {keyword},
    - MetaDescrizione : Qui metti una MetaDescrizione in linea per la SEO relativo a queste keyword in ordine di importanza: {keyword}
    - Published: 1,
    - OgImage : la stessa di Immagine,
    - Excerpt : un excerpt consono, relativo alle keyword: {keyword}
    - TOC: genera una stringa unica con 3 titoli separati da carattere newline `\n`. Non usare liste né markdown. Esempio: "Titolo 1\nTitolo 2\nTitolo 3". Importante, non ti dimenticare dei "\n" per andare a capo!
    - DomandeRisposte: Basandoti sul testo che scriverai su Blocco1, Blocco2 e Blocco3, genera 8 domande generiche (alcune prendile da questo testo purché SEO friendly :' {argomento}') (evita l'over branding, le stesse che le persone possono chiedere a google, simili a quelle di Google snippet che aiutano la SEO) e risposte in questo formato: <section class="faq-section">
  <h2>Domande Frequenti</h2>

  <div class="faq">
    <details>
      <summary>Domanda 1?</summary>
      <p>Risposta menzionando parzialmente la domanda</p>
    </details>

    """
    )

    # Costruiamo i messaggi: istruzioni + CONTEXT_JSON + domanda utente
    print("Generazione messaggio..")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": f"CONTEXT_JSON:\n{context}"},
    ]

    print("Generazione risposta..")
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.8,
    )

    reply = resp.choices[0].message.content
    if "```json" in reply:
      reply = reply.split("```json")[-1].split("```")[0].strip()
    print(reply)

    try:
        print("Risposta > JSON..")
        blog_data = json.loads(reply)
    except json.JSONDecodeError as e:
        print("Errore parsing JSON:", e)
        print("Risposta ricevuta:")
        print(reply)
        raise Exception("Errore parsing JSON: " + str(e))
    
    table = api.table(AIRTABLE_BASE_ID, "Blog")
    try:
       print("Invio ad Airtable..")
       toc = blog_data.get("TOC")

       if isinstance(toc, list):
       # Se è una lista: unisci con newline
         blog_data["TOC"] = "\n".join(toc)

       elif isinstance(toc, str):
       # Se è una stringa multilinea reale (con ritorni a capo veri), normalizzala
         blog_data["TOC"] = "\n".join([line.strip() for line in toc.splitlines() if line.strip()])

       else:
       # Se è altro o None: assegna stringa vuota per evitare errori 
         blog_data["TOC"] = ""
       table.create(blog_data)
       print("Completato!")
       #aggiungi_slug_sitemap(f"{blog_data.get("Slug")}") ** Da riattivare!!

    except Exception as e:
       print(f"Errore Creazione Airtable: {e}")
       raise Exception("Errore Creazione Airtable: " + str(e))
    
#AI_crea_blog_post("App rilevazione presenze personale gratis","app registro presenze, app registro dipendenti", "TeamTime", "www.teamtimeapp.it (home), www.teamtimeapp.it/inizia-prova (prova gratuita 30 giorni)")
#AI_crea_blog_post("una mobile app che aiuta gli chef di tutto il mondo a calcolare il food cost, per capire quanto costa ed il prezzo migliore di vendita","food cost italia, app food cost, quanto costa un piatto, app calcolare food cost", "Food Cost Italia è un'app sviluppata da App Eleveb, permette di inserire gli ingredienti con precisione e calcolare il food cost, suggerisce anche un prezzo di vendita", "www.teamtimeapp.it (link ufficiale), www.teamtimeapp.it/inizia-prova (link per scaricarla negli store apple e android)")
#AI_crea_blog_post("una mobile app che aiuta le strutture ricettive, bar e ristoranti a trovare personale qualificato al bar, la stessa app aiuta bartender esperti, bar managers, mixologist o alle prime armi a trovare offerte di lavoro verificate, di livello sia in italia che all'estero (come dubai, ibiza, svizzera, ecc..), Risolve il problema delle offerte di lavoro e mette in contatto aziende e bartenders e bar managers.", "the bartender app" "offerte lavoro ibiza" "offerta lavoro bartender" "offerte lavoro bar manager", "app The Bartender è un'app sviluppata da App Eleveb, è un app per aziende e bartenders per mettersi in contatto", "www.teamtimeapp.it (link ufficiale), www.teamtimeapp.it/inizia-prova (link per scaricarla negli store apple e android)")
#AI_crea_blog_post(argomento, keyword, context_name, link)#



@app.route('/blog/chi-siamo-contatti')
@app.route('/blog/chi-siamo-contatti/')
def chi_siamo_contatti():
   return render_template('blog/chi-siamo-contatti.html')

@app.route("/2cc8526a8ae94bd0b3a8ce4abf7f4fda.txt")
def serve_indexnow_key():
    return send_from_directory('.', '2cc8526a8ae94bd0b3a8ce4abf7f4fda.txt')
#AI_crea_blog_post("Chakra, come nasce, a che serve, come sbloccarlo? e altre inormazioni utili", "Yoga", "Yoga", "www.viaggiaconsimona.blogspot.com (home page)")



def check_status_abbonamenti(): #**leggere check_status_abbonamenti, legato a run_schedule (per me si può cancellare) in basso il #Aggiornamento: al momento questo lo fa stripe con webhook, il pagamento è automatico e se non effettuato dopo circa un'ora arriva il payment_failed e aggiorna in automatico lo status a Disattivato
    print("Controllo abbonamenti")
    table_name = "Locali Approvati"
    table = api.table(AIRTABLE_BASE_ID, table_name)
    records = table.all()
    for record in records:
      fields = record['fields']
      if fields.get('Status') == "Attivo" and 'Fine Prova' in fields:
        fine_prova_str = fields['Fine Prova']
        try:
            fine_prova = datetime.fromisoformat(fine_prova_str)
            if fine_prova < datetime.now():
                print(f"{fields.get('Locale', 'Sconosciuto')} → Fine Prova SCADUTA: {fine_prova}")
                table.update(record["id"], {"Status": 'Scaduto'})
            else:
                print(f"Prova ancora attiva per {record['fields']['Locale']}")
                
        except Exception as e:
            print(f"Errore nel parsing di Fine Prova per {fields.get('Mail', 'Sconosciuto')}: {e}")
          

#check_status_abbonamenti() Funziona bene, solo che fa il check dell'abbonamento ma può essere che l'abbonamentp è scaduto ma il pagamento di Stripe è andato a buon fine, serve webhook con stripe, Occhio che serve riattivare il threading qui sotto per farlo funzionare

def run_schedule(): #Al momento questo non è attivo, leggi su def check_status_abbonamenti
    schedule.every().day.at("11:45").do(check_status_abbonamenti)
    while True:
        schedule.run_pending()
        time.sleep(5)

def telegram(message):
   url = f"https://api.telegram.org/bot{TELEGRAM_BOT_KEY}/sendMessage"
   if "[REF]" in message:
      payload = {
    "chat_id": "-4908005000",
    "text": message
}
   else:
     payload = {
    "chat_id": CHANNEL_ID,
    "text": message
}
   try:
        response = requests.post(url, data=payload)
        response.raise_for_status()  # Solleva un'eccezione se lo status code è >= 400
   except requests.RequestException as e:
        print(f"Errore durante l'invio a Telegram: {e}")

 
# Avvia il thread per lo scheduling
#threading.Thread(target=run_schedule, daemon=True).start()

def weekly_blog_post():
    print("Controllo post da pubblicare nel blog..")
    table = api.table(AIRTABLE_BASE_ID, "BlogToDo")
    formula = "{Pubblicato} = 'Ready'" 

    records = table.all(formula=formula)

    if records:
        print("Post nel blog da pubblicare trovato..")
        record_id = records[0]["id"]
        fields = records[0]["fields"]

        try:
          AI_crea_blog_post(
            fields.get('Argomento'),
            fields.get('Keywords'),
            fields.get('Contesto'),
            fields.get('Link')
        )

          table.update(record_id, {"Pubblicato": "Si"})
          print(f"Articolo '{fields.get('Argomento')}' pubblicato e aggiornato.")

        except Exception as errore:
          table.update(record_id, {"Pubblicato": f"Errore: {errore}"})
           
    else:
        print("Nessun record da pubblicare.")


weekly_blog_post() #**da togliere

def scheduler_loop():
   schedule.every().day.at("16:44:30").do(weekly_blog_post)
   schedule.every().day.at("16:45:30").do(weekly_blog_post)

   while True:
      schedule.run_pending()
      time.sleep(60)

def avvia_scheduler():
    thread = threading.Thread(target=scheduler_loop, daemon=True)
    thread.start()

if __name__ == '__main__':
    avvia_scheduler()
    app.run(debug=True)






