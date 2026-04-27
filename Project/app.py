from flask import Flask, render_template, request, url_for, redirect, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from datetime import datetime, timezone, timedelta
from functools import wraps
import random

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://admin:13245209@capstone-final.cib6qq46ke9s.us-east-1.rds.amazonaws.com:3306/Capstone_final'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'bob'

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


def phoenix_now():
    return datetime.now(timezone(timedelta(hours=-7))).replace(tzinfo=None)


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
    if last_price_update[0] and (now - last_price_update[0]).seconds < 60:
        return
    if not is_market_open():
        return
    stocks = Stock.query.all()
    for stock in stocks:
        change = random.uniform(-0.05, 0.05)
        new_price = round(float(stock.currentMarketPrice) * (1 + change), 2)
        stock.currentMarketPrice = max(new_price, 0.01)
    db.session.commit()
    last_price_update[0] = now


def process_pending_orders():
    if not is_market_open():
        return

    pending = OrderHistory.query.filter_by(status='pending').all()

    for order in pending:
        customer = Customer.query.get(order.customerId)
        stock = Stock.query.get(order.stockId)

        if not customer or not stock:
            continue

        if order.type == 'buy':
            holding = Portfolio.query.filter_by(
                customerId=order.customerId, stockId=order.stockId
            ).first()
            if holding:
                holding.quantity += order.quantity
            else:
                db.session.add(Portfolio(
                    customerId=order.customerId,
                    stockId=order.stockId,
                    quantity=order.quantity
                ))
            order.price = float(stock.currentMarketPrice)
            order.totalValue = round(float(stock.currentMarketPrice) * order.quantity, 2)
            order.status = 'completed'

        elif order.type == 'sell':
            total = round(float(stock.currentMarketPrice) * order.quantity, 2)
            customer.availableFunds = round(float(customer.availableFunds) + total, 2)
            order.price = float(stock.currentMarketPrice)
            order.totalValue = total
            order.status = 'completed'

    db.session.commit()


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
    process_pending_orders()
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
    process_pending_orders()
    stocks = Stock.query.filter(Stock.quantity > 0).order_by(Stock.ticker).all()
    error = None

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

                if is_market_open():
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
                else:
                    db.session.add(OrderHistory(
                        customerId=current_user.id,
                        stockId=stock.id,
                        type='buy',
                        quantity=quantity,
                        price=float(stock.currentMarketPrice),
                        totalValue=total,
                        status='pending'
                    ))
                    db.session.commit()
                    flash(f'Market is closed. Buy order for {quantity} share(s) of {stock.ticker} queued and will execute when market opens.', 'warning')

                return redirect(url_for('buy'))

    return render_template('buy.html', stocks=stocks, error=error, market_open=is_market_open())


@app.route('/sell', methods=['GET', 'POST'])
@login_required
def sell():
    process_pending_orders()
    holdings = (
        Portfolio.query
        .filter_by(customerId=current_user.id)
        .filter(Portfolio.quantity > 0)
        .all()
    )
    error = None

    if request.method == 'POST':
        portfolio_id = request.form.get('portfolio_id')
        try:
            quantity = int(request.form.get('quantity', 0))
        except ValueError:
            quantity = 0

        holding = Portfolio.query.get(portfolio_id)

        if not holding or holding.customerId != current_user.id:
            error = 'Invalid selection.'
        elif quantity <= 0:
            error = 'Quantity must be at least 1.'
        elif quantity > holding.quantity:
            error = f'You only own {holding.quantity} share(s) of {holding.stock.ticker}.'
        else:
            holding.quantity -= quantity
            holding.stock.quantity += quantity

            if is_market_open():
                total = round(float(holding.stock.currentMarketPrice) * quantity, 2)
                current_user.availableFunds = round(float(current_user.availableFunds) + total, 2)
                db.session.add(OrderHistory(
                    customerId=current_user.id,
                    stockId=holding.stockId,
                    type='sell',
                    quantity=quantity,
                    price=float(holding.stock.currentMarketPrice),
                    totalValue=total,
                    status='completed'
                ))
                db.session.commit()
                flash(f'Sold {quantity} share(s) of {holding.stock.ticker} for ${total:.2f}.', 'success')
            else:
                db.session.add(OrderHistory(
                    customerId=current_user.id,
                    stockId=holding.stockId,
                    type='sell',
                    quantity=quantity,
                    price=float(holding.stock.currentMarketPrice),
                    totalValue=0,
                    status='pending'
                ))
                db.session.commit()
                flash(f'Market is closed. Sell order for {quantity} share(s) of {holding.stock.ticker} queued and will execute when market opens.', 'warning')

            return redirect(url_for('sell'))

    return render_template('sell.html', holdings=holdings, error=error, market_open=is_market_open())


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

    if order.type == 'buy':
        current_user.availableFunds = round(float(current_user.availableFunds) + float(order.totalValue), 2)
        holding = Portfolio.query.filter_by(
            customerId=current_user.id, stockId=order.stockId
        ).first()
        if holding:
            holding.quantity -= order.quantity
        stock = Stock.query.get(order.stockId)
        if stock:
            stock.quantity += order.quantity

    elif order.type == 'sell':
        holding = Portfolio.query.filter_by(
            customerId=current_user.id, stockId=order.stockId
        ).first()
        if holding:
            holding.quantity += order.quantity
        stock = Stock.query.get(order.stockId)
        if stock:
            stock.quantity -= order.quantity
        current_user.availableFunds = round(float(current_user.availableFunds) - float(order.totalValue), 2)

    order.status = 'cancelled'
    db.session.commit()
    flash('Order cancelled successfully.', 'success')
    return redirect(url_for('history'))


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
    return render_template('portfolio.html', holdings=holdings)


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


@app.route('/manage_stocks', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_stocks():
    stocks = Stock.query.order_by(Stock.ticker).all()
    error = None

    if request.method == 'POST':
        action = request.form.get('action')
        stock_id = request.form.get('stock_id')

        if action == 'add':
            ticker = request.form.get('ticker', '').strip().upper()
            name = request.form.get('companyName', '').strip()
            price = request.form.get('currentMarketPrice', '')
            qty = request.form.get('quantity', '')

            if not all([ticker, name, price, qty]):
                error = 'All fields are required.'
            elif Stock.query.filter_by(ticker=ticker).first():
                error = f'Ticker {ticker} already exists.'
            else:
                db.session.add(Stock(
                    ticker=ticker,
                    companyName=name,
                    currentMarketPrice=round(float(price), 2),
                    quantity=int(qty)
                ))
                db.session.commit()
                flash(f'{ticker} added successfully.', 'success')
                return redirect(url_for('manage_stocks'))

        elif action == 'edit':
            stock = Stock.query.get(stock_id)
            if stock:
                stock.companyName = request.form.get('companyName', '').strip()
                stock.currentMarketPrice = round(float(request.form.get('currentMarketPrice', stock.currentMarketPrice)), 2)
                stock.quantity = int(request.form.get('quantity', stock.quantity))
                db.session.commit()
                flash(f'{stock.ticker} updated successfully.', 'success')
                return redirect(url_for('manage_stocks'))

        elif action == 'delete':
            stock = Stock.query.get(stock_id)
            if stock:
                ticker = stock.ticker
                Portfolio.query.filter_by(stockId=stock.id).delete()
                OrderHistory.query.filter_by(stockId=stock.id).delete()
                db.session.delete(stock)
                db.session.commit()
                flash(f'{ticker} deleted.', 'success')
                return redirect(url_for('manage_stocks'))

    return render_template('manage_stocks.html', stocks=stocks, error=error)


@app.route('/market_hours', methods=['GET', 'POST'])
@login_required
@admin_required
def market_hours():
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    working_days = {wd.dayOfWeek: wd for wd in WorkingDay.query.all()}
    error = None

    if request.method == 'POST':
        start = request.form.get('startTime')
        end = request.form.get('endTime')

        if not start or not end:
            error = 'Start and end time are required.'
        else:
            selected_days = request.form.getlist('days')
            WorkingDay.query.delete()
            for day in selected_days:
                db.session.add(WorkingDay(
                    dayOfWeek=day,
                    startTime=datetime.strptime(start, '%H:%M').time(),
                    endTime=datetime.strptime(end, '%H:%M').time()
                ))
            db.session.commit()
            flash('Market hours saved.', 'success')
            return redirect(url_for('market_hours'))

    return render_template('market_hours.html', days=days, working_days=working_days, error=error)


@app.route('/exceptions', methods=['GET', 'POST'])
@login_required
@admin_required
def exceptions():
    all_exceptions = Exception.query.order_by(Exception.holidayDate).all()
    error = None

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            date = request.form.get('holidayDate')
            reason = request.form.get('reason', '').strip()

            if not date or not reason:
                error = 'Date and reason are required.'
            elif Exception.query.filter_by(holidayDate=date).first():
                error = 'An exception for that date already exists.'
            else:
                db.session.add(Exception(
                    holidayDate=datetime.strptime(date, '%Y-%m-%d').date(),
                    reason=reason
                ))
                db.session.commit()
                flash('Exception added.', 'success')
                return redirect(url_for('exceptions'))

        elif action == 'delete':
            exc = Exception.query.get(request.form.get('exception_id'))
            if exc:
                db.session.delete(exc)
                db.session.commit()
                flash('Exception removed.', 'success')
                return redirect(url_for('exceptions'))

    return render_template('exceptions.html', exceptions=all_exceptions, error=error)


if __name__ == '__main__':
    app.run(debug=True)