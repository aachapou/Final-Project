from flask import Flask, render_template, request, url_for, redirect, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from datetime import datetime, timezone, timedelta
from functools import wraps
import random

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:13245209Red@localhost/Capstone'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'bob'

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


def phoenix_now():
    return datetime.now(timezone(timedelta(hours=-5))).replace(tzinfo=None)


class Customer(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column(db.String(250), nullable=False)
    email = db.Column(db.String(250), unique=True, nullable=False)
    username = db.Column(db.String(250), unique=True, nullable=False)
    hashedPassword = db.Column(db.String(250), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='user')
    availableFunds = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    createdAt = db.Column(db.DateTime, nullable=False, default=phoenix_now)


class Stock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticker = db.Column(db.String(10), unique=True, nullable=False)
    companyName = db.Column(db.String(250), nullable=False)
    currentMarketPrice = db.Column(db.Numeric(10, 2), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    createdAt = db.Column(db.DateTime, nullable=False, default=phoenix_now)


class Portfolio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customerId = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    stockId = db.Column(db.Integer, db.ForeignKey('stock.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    customer = db.relationship('Customer', backref='portfolio')
    stock = db.relationship('Stock', backref='portfolio')


class OrderHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customerId = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    stockId = db.Column(db.Integer, db.ForeignKey('stock.id'), nullable=True)
    type = db.Column(db.String(10), nullable=False)
    quantity = db.Column(db.Integer, nullable=True)
    price = db.Column(db.Numeric(10, 2), nullable=True)
    totalValue = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(10), nullable=False, default='completed')
    createdAt = db.Column(db.DateTime, nullable=False, default=phoenix_now)

    customer = db.relationship('Customer', backref='orders')
    stock = db.relationship('Stock', backref='orders')


class WorkingDay(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dayOfWeek = db.Column(db.String(10), nullable=False, unique=True)
    startTime = db.Column(db.Time, nullable=False)
    endTime = db.Column(db.Time, nullable=False)


class Exception(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    holidayDate = db.Column(db.Date, nullable=False, unique=True)
    reason = db.Column(db.String(250), nullable=False)
    createdAt = db.Column(db.DateTime, nullable=False, default=phoenix_now)


with app.app_context():
    db.create_all()


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Admin access required.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated


def is_market_open():
    now = phoenix_now()
    day = now.strftime('%A')
    wd = WorkingDay.query.filter_by(dayOfWeek=day).first()
    if not wd:
        return False
    exc = Exception.query.filter_by(holidayDate=now.date()).first()
    if exc:
        return False
    return wd.startTime <= now.time() <= wd.endTime


last_price_update = [None]

def update_stock_prices():
    now = phoenix_now()
    if last_price_update[0] and (now - last_price_update[0]).seconds < 2:
        return
    if not is_market_open():
        return
    stocks = Stock.query.all()
    for stock in stocks:
        change = random.uniform(-0.2, 0.2)
        new_price = round(float(stock.currentMarketPrice) * (1 + change), 2)
        stock.currentMarketPrice = max(new_price, 0.01)
    db.session.commit()
    last_price_update[0] = now


@login_manager.user_loader
def load_user(user_id):
    return Customer.query.get(int(user_id))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            error = 'Please fill in all fields.'
        else:
            user = Customer.query.filter_by(username=username).first()
            if user and bcrypt.check_password_hash(user.hashedPassword, password):
                login_user(user)
                return redirect(url_for('home'))
            else:
                error = 'Invalid username or password.'

    return render_template('login.html', error=error)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    error = None
    if request.method == 'POST':
        fullname = request.form.get('fullname', '').strip()
        email = request.form.get('email', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not all([fullname, email, username, password, confirm_password]):
            error = 'All fields are required.'
        elif password != confirm_password:
            error = 'Passwords do not match.'
        elif Customer.query.filter_by(username=username).first():
            error = 'Username already taken.'
        elif Customer.query.filter_by(email=email).first():
            error = 'Email already in use.'
        else:
            hashed = bcrypt.generate_password_hash(password).decode('utf-8')
            customer = Customer(
                fullname=fullname,
                email=email,
                username=username,
                hashedPassword=hashed,
                role='user'
            )
            db.session.add(customer)
            db.session.commit()
            return redirect(url_for('login'))

    return render_template('sign_up.html', error=error)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def home():
    update_stock_prices()
    holdings = (
        Portfolio.query
        .filter_by(customerId=current_user.id)
        .filter(Portfolio.quantity > 0)
        .all()
    )
    recent_orders = (
        OrderHistory.query
        .filter_by(customerId=current_user.id)
        .order_by(OrderHistory.createdAt.desc())
        .limit(5)
        .all()
    )
    portfolio_value = sum(float(h.stock.currentMarketPrice) * h.quantity for h in holdings)
    market_open = is_market_open()
    return render_template('home.html',
        holdings=holdings,
        recent_orders=recent_orders,
        portfolio_value=round(portfolio_value, 2),
        market_open=market_open
    )

@app.route('/portfolio')
@login_required
def portfolio():
    update_stock_prices()
    holdings = (
        Portfolio.query
        .filter_by(customerId=current_user.id)
        .filter(Portfolio.quantity > 0)
        .all()
    )
    portfolio_value = sum(float(h.stock.currentMarketPrice) * h.quantity for h in holdings)
    return render_template(
        'portfolio.html',
        holdings=holdings,
        portfolio_value=round(portfolio_value, 2)
    )

@app.route('/history')
@login_required
def history():
    orders = (
        OrderHistory.query
        .filter_by(customerId=current_user.id)
        .order_by(OrderHistory.createdAt.desc())
        .all()
    )
    return render_template('history.html', orders=orders)

@app.route('/deposit', methods=['GET', 'POST'])
@login_required
def deposit():
    error = None
    if request.method == 'POST':
        try:
            amount = round(float(request.form.get('amount', 0)), 2)
        except ValueError:
            amount = 0

        if amount <= 0:
            error = 'Please enter a valid amount.'
        else:
            current_user.availableFunds = round(float(current_user.availableFunds) + amount, 2)
            db.session.add(OrderHistory(
                customerId=current_user.id,
                type='deposit',
                totalValue=amount,
                status='completed'
            ))
            db.session.commit()
            flash(f'Successfully deposited ${amount:.2f}.', 'success')
            return redirect(url_for('deposit'))

    return render_template('deposit.html', error=error)


@app.route('/withdraw', methods=['GET', 'POST'])
@login_required
def withdraw():
    error = None
    if request.method == 'POST':
        try:
            amount = round(float(request.form.get('amount', 0)), 2)
        except ValueError:
            amount = 0

        if amount <= 0:
            error = 'Please enter a valid amount.'
        elif amount > float(current_user.availableFunds):
            error = f'Insufficient funds. You have ${current_user.availableFunds:.2f} available.'
        else:
            current_user.availableFunds = round(float(current_user.availableFunds) - amount, 2)
            db.session.add(OrderHistory(
                customerId=current_user.id,
                type='withdraw',
                totalValue=amount,
                status='completed'
            ))
            db.session.commit()
            flash(f'Successfully withdrew ${amount:.2f}.', 'success')
            return redirect(url_for('withdraw'))

    return render_template('withdraw.html', error=error)


@app.route('/buy', methods=['GET', 'POST'])
@login_required
def buy():
    update_stock_prices()
    stocks = Stock.query.filter(Stock.quantity > 0).order_by(Stock.ticker).all()
    error = None

    if not is_market_open():
        error = 'Market is currently closed. Trading is not allowed right now.'
        return render_template('buy.html', stocks=stocks, error=error)

    if request.method == 'POST':
        stock_id = request.form.get('stock_id')
        try:
            quantity = int(request.form.get('quantity', 0))
        except ValueError:
            quantity = 0

        stock = Stock.query.get(stock_id)

        if not stock:
            error = 'Invalid stock selected.'
        elif quantity <= 0:
            error = 'Quantity must be at least 1.'
        elif quantity > stock.quantity:
            error = f'Only {stock.quantity} share(s) of {stock.ticker} available.'
        else:
            total = round(float(stock.currentMarketPrice) * quantity, 2)
            if float(current_user.availableFunds) < total:
                error = f'Insufficient funds. Need ${total:.2f}, have ${current_user.availableFunds:.2f}.'
            else:
                current_user.availableFunds = round(float(current_user.availableFunds) - total, 2)
                stock.quantity -= quantity

                holding = Portfolio.query.filter_by(
                    customerId=current_user.id, stockId=stock.id
                ).first()

                if holding:
                    holding.quantity += quantity
                else:
                    db.session.add(Portfolio(
                        customerId=current_user.id,
                        stockId=stock.id,
                        quantity=quantity
                    ))

                db.session.add(OrderHistory(
                    customerId=current_user.id,
                    stockId=stock.id,
                    type='buy',
                    quantity=quantity,
                    price=float(stock.currentMarketPrice),
                    totalValue=total,
                    status='completed'
                ))

                db.session.commit()
                flash(f'Bought {quantity} share(s) of {stock.ticker} for ${total:.2f}.', 'success')
                return redirect(url_for('buy'))

    return render_template('buy.html', stocks=stocks, error=error)


@app.route('/sell', methods=['GET', 'POST'])
@login_required
def sell():
    holdings = (
        Portfolio.query
        .filter_by(customerId=current_user.id)
        .filter(Portfolio.quantity > 0)
        .all()

@app.route('/cancel_order/<int:order_id>', methods=['POST'])
@login_required
def cancel_order(order_id):
    order = OrderHistory.query.get(order_id)

    if not order or order.customerId != current_user.id:
        flash('Order not found.', 'danger')
        return redirect(url_for('history'))

    if order.status != 'pending':
        flash('Only pending orders can be cancelled.', 'danger')
        return redirect(url_for('history'))

    order.status = 'cancelled'
    db.session.commit()
    flash('Order cancelled successfully.', 'success')
    return redirect(url_for('history'))

if __name__ == "__main__":
    app.run(debug=True)