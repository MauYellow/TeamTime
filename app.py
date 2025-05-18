import stripe
import os
from flask import Flask, render_template, redirect, url_for, request, jsonify
from flask_mail import Mail, Message
from config import STRIPE_SECRET_KEY, STRIPE_PRICE_ID, STRIPE_WEBHOOK_SECRET, MAIL_USERNAME, MAIL_PASSWORD
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

stripe.api_key = STRIPE_SECRET_KEY
STRIPE_PRICE_ID = STRIPE_PRICE_ID #"price_1RN9mhEF8NjwgIEO4ZGym71S" #reale > "price_1RN9QQEF8NjwgIEOh6LgsLD4"
STRIPE_WEBHOOK_SECRET = STRIPE_WEBHOOK_SECRET #'whsec_b7142045be6eda2db162e890c9acd6ac2d348dfd24f4401b9d334eb8a672e781' #di prova nel locale, scade dopo 90 giorni

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

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

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

if __name__ == '__main__':
    app.run(debug=True)

