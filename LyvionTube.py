# LyvionTube.py - Archivo principal de la aplicación Flask para LyvionTube
# Código completo y funcional. Instala dependencias con: pip install flask flask-sqlalchemy werkzeug stripe
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, g
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
from datetime import datetime, timedelta
import stripe  # Agrega esto para pagos

app = Flask(__name__)
app.config['SECRET_KEY'] = 'tu_clave_secreta_aqui'  # Cambia esto en producción
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///lyviontube.db')  # Para Render o local
app.config['UPLOAD_FOLDER'] = 'uploads'  # Carpeta para videos y fotos
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB límite para uploads
app.config['STRIPE_PUBLIC_KEY'] = 'tu_clave_publica_de_stripe'  # Agrega tu clave pública de Stripe
app.config['STRIPE_SECRET_KEY'] = 'tu_clave_secreta_de_stripe'  # Agrega tu clave secreta de Stripe

stripe.api_key = app.config['STRIPE_SECRET_KEY']  # Configura Stripe

db = SQLAlchemy(app)

# Crear carpeta de uploads si no existe
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Modelos de base de datos
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    nickname = db.Column(db.String(80), nullable=True)  # Sobrenombre editable
    password = db.Column(db.String(120), nullable=False)
    profile_pic = db.Column(db.String(120), default='default.jpg')
    bio = db.Column(db.Text, default='Sin biografía')
    plan = db.Column(db.String(20), default='Gratis')  # Gratis, Básico, Pro, VIP
    plan_expiry = db.Column(db.DateTime, nullable=True)  # Fecha de expiración para Básico
    is_moderator = db.Column(db.Boolean, default=False)
    channels = db.relationship('Channel', backref='owner', lazy=True)
    videos = db.relationship('Video', backref='uploader', lazy=True)
    followed_channels = db.relationship('Follow', foreign_keys='Follow.user_id', backref='follower', lazy=True)

class Channel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, default='')
    followers = db.Column(db.BigInteger, default=0)  # Cambiado a BigInteger
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    videos = db.relationship('Video', backref='channel', lazy=True)
    followed_by = db.relationship('Follow', foreign_keys='Follow.channel_id', backref='followed_channel', lazy=True)

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    filename = db.Column(db.String(120), nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)  # Nueva columna para fecha de subida
    uploader_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    channel_id = db.Column(db.Integer, db.ForeignKey('channel.id'), nullable=False)
    comments = db.relationship('Comment', backref='video', lazy=True)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref='comments')  # Relación con User

class Follow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    channel_id = db.Column(db.Integer, db.ForeignKey('channel.id'), nullable=False)

class Like(db.Model):  # Nueva tabla para likes/dislikes por usuario
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # 'like' or 'dislike'

# Funciones auxiliares
def format_followers(num):
    if num >= 1000000:
        return f"{num/1000000:.1f}M"
    elif num >= 1000:
        return f"{num//1000}k"
    return str(num)

def allowed_file(filename, extensions=['mp4', 'mp3']):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in extensions

def has_active_plan(user):
    if user.plan in ['Pro', 'VIP']:
        return True
    if user.plan == 'Básico' and user.plan_expiry and user.plan_expiry > datetime.utcnow():
        return True
    return False

def get_video_likes(video_id):
    return Like.query.filter_by(video_id=video_id, type='like').count()

def get_video_dislikes(video_id):
    return Like.query.filter_by(video_id=video_id, type='dislike').count()

@app.before_request
def load_current_user():
    g.current_user = User.query.get(session.get('user_id')) if session.get('user_id') else None

# Rutas
@app.route('/')
def home():
    videos = Video.query.all()
    for video in videos:
        video.likes = get_video_likes(video.id)
        video.dislikes = get_video_dislikes(video.id)
    return render_template('home.html', videos=videos, format_followers=format_followers, current_user=g.current_user)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        nickname = request.form.get('nickname', username)
        
        # Validaciones: No espacios en username/password para usuarios normales
        if ' ' in username or ' ' in password:
            flash('El nombre de usuario y la contraseña no pueden contener espacios.', 'error')
            return redirect(url_for('register'))
        
        # Verificar si ya existe
        if User.query.filter_by(username=username).first():
            flash('El nombre de usuario ya existe.', 'error')
            return redirect(url_for('register'))
        
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(username=username, nickname=nickname, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        flash('Registro exitoso. Inicia sesión.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', current_user=g.current_user)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            flash('Inicio de sesión exitoso.', 'success')
            return redirect(url_for('home'))
        flash('Credenciales incorrectas.', 'error')
    return render_template('login.html', current_user=g.current_user)

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('Sesión cerrada.', 'success')
    return redirect(url_for('home'))

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    total_followers = sum(channel.followers for channel in user.channels)
    if request.method == 'POST':
        user.nickname = request.form.get('nickname', user.nickname)
        user.bio = request.form.get('bio', user.bio)
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and allowed_file(file.filename, ['jpg', 'png']):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                user.profile_pic = filename
        db.session.commit()
        flash('Perfil actualizado.', 'success')
    return render_template('profile.html', user=user, format_followers=format_followers, total_followers=total_followers, current_user=g.current_user)

@app.route('/channel/<int:channel_id>', methods=['GET', 'POST'])
def channel(channel_id):
    channel = Channel.query.get_or_404(channel_id)
    user = g.current_user
    is_following = user and Follow.query.filter_by(user_id=user.id, channel_id=channel_id).first()
    if request.method == 'POST' and user:
        if request.form.get('action') == 'follow' and not is_following:
            follow = Follow(user_id=user.id, channel_id=channel_id)
            db.session.add(follow)
            channel.followers += 1
            db.session.commit()
            flash('Ahora sigues este canal. Contador actualizado.', 'success')
        elif request.form.get('action') == 'unfollow' and is_following:
            Follow.query.filter_by(user_id=user.id, channel_id=channel_id).delete()
            channel.followers -= 1
            db.session.commit()
            flash('Dejaste de seguir este canal. Contador actualizado.', 'success')
        elif request.form.get('action') == 'delete_video':
            video_id = request.form['video_id']
            video = Video.query.get(video_id)
            if video and video.uploader_id == user.id:
                db.session.delete(video)
                db.session.commit()
                flash('Video eliminado.', 'success')
            else:
                flash('No puedes eliminar este video.', 'error')
        return redirect(url_for('channel', channel_id=channel_id))
    return render_template('channel.html', channel=channel, format_followers=format_followers, is_following=is_following, user=user, current_user=g.current_user)

@app.route('/video/<int:video_id>', methods=['GET', 'POST'])
def video(video_id):
    video = Video.query.get_or_404(video_id)
    channel = video.channel  # Obtener el canal del video
    user = g.current_user
    is_following = user and Follow.query.filter_by(user_id=user.id, channel_id=channel.id).first()
    if request.method == 'POST':
        if not user:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return {'error': 'Debes iniciar sesión.'}, 401
            flash('Debes iniciar sesión.', 'error')
            return redirect(url_for('login'))
        existing_like = Like.query.filter_by(user_id=user.id, video_id=video_id).first()
        response_data = {}
        if request.form.get('action') == 'like':
            if existing_like and existing_like.type == 'like':
                db.session.delete(existing_like)
                response_data['message'] = 'Like quitado.'
            elif existing_like and existing_like.type == 'dislike':
                existing_like.type = 'like'
                response_data['message'] = 'Cambiado a like.'
            else:
                new_like = Like(user_id=user.id, video_id=video_id, type='like')
                db.session.add(new_like)
                response_data['message'] = 'Like dado.'
        elif request.form.get('action') == 'dislike':
            if existing_like and existing_like.type == 'dislike':
                db.session.delete(existing_like)
                response_data['message'] = 'Dislike quitado.'
            elif existing_like and existing_like.type == 'like':
                existing_like.type = 'dislike'
                response_data['message'] = 'Cambiado a dislike.'
            else:
                new_like = Like(user_id=user.id, video_id=video_id, type='dislike')
                db.session.add(new_like)
                response_data['message'] = 'Dislike dado.'
        elif request.form.get('action') == 'follow_channel':
            if not is_following:
                follow = Follow(user_id=user.id, channel_id=channel.id)
                db.session.add(follow)
                channel.followers += 1
                response_data['message'] = 'Ahora sigues este canal.'
                response_data['is_following'] = True
            else:
                response_data['message'] = 'Ya sigues este canal.'
        elif request.form.get('action') == 'unfollow_channel':
            if is_following:
                Follow.query.filter_by(user_id=user.id, channel_id=channel.id).delete()
                channel.followers -= 1
                response_data['message'] = 'Dejaste de seguir este canal.'
                response_data['is_following'] = False
            else:
                response_data['message'] = 'No sigues este canal.'
        elif request.form.get('action') == 'delete_video':
            if video.uploader_id == user.id:
                db.session.delete(video)
                db.session.commit()
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return {'message': 'Video eliminado.', 'redirect': url_for('home')}, 200
                flash('Video eliminado.', 'success')
                return redirect(url_for('home'))
            else:
                response_data['error'] = 'No puedes eliminar este video.'
        elif request.form.get('comment'):
            new_comment = Comment(content=request.form['comment'], video_id=video_id, user_id=user.id)
            db.session.add(new_comment)
            response_data['message'] = 'Comentario agregado.'
            response_data['comment'] = {
                'content': request.form['comment'],
                'user_nickname': user.nickname
            }
        db.session.commit()
        # Actualizar contadores para respuesta
        response_data['likes'] = get_video_likes(video.id)
        response_data['dislikes'] = get_video_dislikes(video.id)
        response_data['followers'] = channel.followers
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return response_data, 200
        return redirect(url_for('video', video_id=video_id))
    video.likes = get_video_likes(video.id)
    video.dislikes = get_video_dislikes(video.id)
    show_ad = g.current_user and not has_active_plan(g.current_user)
    return render_template('video.html', video=video, channel=channel, is_following=is_following, show_ad=show_ad, format_followers=format_followers, current_user=g.current_user)

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    channels = Channel.query.filter_by(owner_id=user.id).all()  # Cualquier usuario puede subir a sus canales
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        channel_id = request.form['channel_id']
        file = request.files['video']
        if file and allowed_file(file.filename, ['mp4', 'mp3']):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            new_video = Video(title=title, description=description, filename=filename, uploader_id=user.id, channel_id=channel_id)
            db.session.add(new_video)
            db.session.commit()
            flash('Video subido.', 'success')
            return redirect(url_for('home'))
    return render_template('upload.html', channels=channels, current_user=g.current_user)

@app.route('/search')
def search():
    query = request.args.get('q', '').lower()
    videos = Video.query.filter((Video.title.contains(query)) | (Video.description.contains(query))).all()
    channels = Channel.query.filter((Channel.name.contains(query)) | (Channel.description.contains(query))).all()
    for video in videos:
        video.likes = get_video_likes(video.id)
        video.dislikes = get_video_dislikes(video.id)
    return render_template('search.html', videos=videos, channels=channels, query=query, format_followers=format_followers, current_user=g.current_user)

@app.route('/plans', methods=['GET', 'POST'])
def plans():
    if request.method == 'POST' and g.current_user:
        plan = request.form['plan']
        # Redirigir a confirmar en lugar de activar directamente
        return redirect(url_for('confirm_plan', plan=plan))
    return render_template('plans.html', current_user=g.current_user)

@app.route('/confirm_plan/<plan>', methods=['GET', 'POST'])
def confirm_plan(plan):
    if not g.current_user:
        return redirect(url_for('login'))
    if request.method == 'POST':
        if request.form.get('action') == 'confirm':
            # Redirigir a pago
            return redirect(url_for('pay', plan=plan))
        elif request.form.get('action') == 'back':
            return redirect(url_for('plans'))
    # Detalles del plan para mostrar
    plan_details = {
        'Básico': {'price': '$4.99/mes', 'features': ['Sube videos ilimitados', 'Acceso a videos premium', 'Sin anuncios en tus videos', 'Dura 1 mes']},
        'Pro': {'price': '$9.99/mes', 'features': ['Todo lo de Básico', 'Personalización avanzada de canales', 'Soporte prioritario', 'Permanente']},
        'VIP': {'price': '$19.99/mes', 'features': ['Todo lo de Pro', 'Acceso temprano a nuevas funciones', 'Soporte VIP 24/7', 'Estadísticas avanzadas']}
    }
    return render_template('confirm_plan.html', plan=plan, details=plan_details.get(plan, {}), current_user=g.current_user)

@app.route('/pay/<plan>', methods=['GET', 'POST'])
def pay(plan):
    if not g.current_user:
        return redirect(url_for('login'))
    if request.method == 'POST':
        # Procesar pago con Stripe
        try:
            # Crear un cargo (ejemplo simple; ajusta según tus necesidades)
            charge = stripe.Charge.create(
                amount=499,  # Monto en centavos (ej. $4.99)
                currency='usd',
                description=f'Pago por plan {plan}',
                source=request.form['stripeToken']
            )
            # Si el pago es exitoso, activar el plan
            g.current_user.plan = plan
            if plan == 'Básico':
                g.current_user.plan_expiry = datetime.utcnow() + timedelta(days=30)
            else:
                g.current_user.plan_expiry = None
            db.session.commit()
            flash(f'Pago exitoso. Plan {plan} activado.', 'success')
            return redirect(url_for('home'))
        except stripe.error.CardError as e:
            flash(f'Error en el pago: {e.error.message}', 'error')
            return redirect(url_for('pay', plan=plan))
    return render_template('pay.html', plan=plan, key=app.config['STRIPE_PUBLIC_KEY'], current_user=g.current_user)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if 'user_id' not in session or User.query.get(session['user_id']).username != 'LyvionStudio':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('home'))
    users = User.query.all()
    channels = Channel.query.all()
    videos = Video.query.all()
    for video in videos:
        video.likes = get_video_likes(video.id)
        video.dislikes = get_video_dislikes(video.id)
    if request.method == 'POST':
        action = request.form['action']
        if action == 'delete_user':
            user_id = request.form['user_id']
            user = User.query.get(user_id)
            db.session.delete(user)
            db.session.commit()
            flash('Usuario eliminado.', 'success')
        elif action == 'assign_moderator':
            user_id = request.form['user_id']
            user = User.query.get(user_id)
            user.is_moderator = True
            db.session.commit()
            flash('Moderador asignado.', 'success')
        elif action == 'delete_comment':
            comment_id = request.form['comment_id']
            comment = Comment.query.get(comment_id)
            db.session.delete(comment)
            db.session.commit()
            flash('Comentario eliminado.', 'success')
        elif action == 'add_followers_user':
            user_id = request.form['user_id']
            amount = int(request.form['amount'])
            user = User.query.get(user_id)
            # Agregar seguidores a todos los canales del usuario
            for channel in user.channels:
                channel.followers += amount
            db.session.commit()
            flash(f'Agregados {amount} seguidores a los canales de {user.username}.', 'success')
        elif action == 'add_followers_channel':
            channel_id = request.form['channel_id']
            amount = int(request.form['amount'])
            channel = Channel.query.get(channel_id)
            channel.followers += amount
            db.session.commit()
            flash(f'Agregados {amount} seguidores al canal {channel.name}.', 'success')
        elif action == 'delete_channel':
            channel_id = request.form['channel_id']
            channel = Channel.query.get(channel_id)
            # Eliminar videos asociados al canal antes de eliminar el canal
            Video.query.filter_by(channel_id=channel_id).delete()
            db.session.delete(channel)
            db.session.commit()
            flash(f'Canal {channel.name} y sus videos eliminados.', 'success')
        elif action == 'delete_video':
            video_id = request.form['video_id']
            video = Video.query.get(video_id)
            db.session.delete(video)
            db.session.commit()
            flash('Video eliminado.', 'success')
        return redirect(url_for('admin'))
    return render_template('admin.html', users=users, channels=channels, videos=videos, format_followers=format_followers, current_user=g.current_user)

@app.route('/manage_users', methods=['GET', 'POST'])
def manage_users():
    if 'user_id' not in session or User.query.get(session['user_id']).username != 'LyvionStudio':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('home'))
    query = request.args.get('q', '')
    users = User.query.filter(User.username.contains(query)).all() if query else User.query.all()
    # Calcular total_followers para cada usuario
    for user in users:
        user.total_followers = sum(channel.followers for channel in user.channels)
    selected_user = None
    if request.method == 'POST':
        user_id = request.form['user_id']
        selected_user = User.query.get(user_id)
        action = request.form['action']
        if action == 'add_followers':
            amount = int(request.form['amount'])
            for channel in selected_user.channels:
                channel.followers += amount
            db.session.commit()
            flash(f'Agregados {amount} seguidores a los canales de {selected_user.username}.', 'success')
        elif action == 'remove_followers':
            amount = int(request.form['amount'])
            for channel in selected_user.channels:
                channel.followers = max(0, channel.followers - amount)
            db.session.commit()
            flash(f'Removidos {amount} seguidores de los canales de {selected_user.username}.', 'success')
        elif action == 'assign_moderator':
            selected_user.is_moderator = True
            db.session.commit()
            flash(f'{selected_user.username} asignado como moderador.', 'success')
        elif action == 'remove_moderator':
            selected_user.is_moderator = False
            db.session.commit()
            flash(f'{selected_user.username} removido como moderador.', 'success')
        return redirect(url_for('manage_users', q=query))
    return render_template('manage_users.html', users=users, query=query, selected_user=selected_user, format_followers=format_followers, current_user=g.current_user)

@app.route('/create_channel', methods=['GET', 'POST'])
def create_channel():
    if 'user_id' not in session or User.query.get(session['user_id']).username != 'LyvionStudio':
        flash('Solo LyvionStudio puede crear canales.', 'error')
        return redirect(url_for('home'))
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        new_channel = Channel(name=name, description=description, owner_id=session['user_id'])
        db.session.add(new_channel)
        db.session.commit()
        flash('Canal creado.', 'success')
        return redirect(url_for('home'))
    return render_template('create_channel.html', current_user=g.current_user)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Inicializar base de datos y crear cuenta LyvionStudio con muchos seguidores y videos graciosos
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='LyvionStudio').first():
        hashed_password = generate_password_hash('LyvionStudiosJuan', method='pbkdf2:sha256')
        lyvion = User(username='LyvionStudio', nickname='LyvionStudio', password=hashed_password, plan='VIP')
        db.session.add(lyvion)
        db.session.commit()
        # Crear canales de ejemplo con muchos seguidores
        channel1 = Channel(name='Canal Oficial Lyvion', description='Videos épicos de la comunidad.', owner_id=lyvion.id, followers=1200000)
        channel2 = Channel(name='Tutoriales Pro', description='Aprende con nosotros.', owner_id=lyvion.id, followers=800000)
        channel3 = Channel(name='Canal Gracioso', description='Videos graciosos para reírte.', owner_id=lyvion.id, followers=500000)
        db.session.add(channel1)
        db.session.add(channel2)
        db.session.add(channel3)
        db.session.commit()
        
        # Crear videos de ejemplo graciosos
        video1 = Video(title='Video Gracioso 1', description='Un video muy gracioso que te hará reír.', filename='default.mp4', uploader_id=lyvion.id, channel_id=channel3.id)
        video2 = Video(title='Video Gracioso 2', description='Otro video gracioso con chistes divertidos.', filename='default.mp4', uploader_id=lyvion.id, channel_id=channel3.id)
        video3 = Video(title='Tutorial Gracioso', description='Un tutorial gracioso sobre cómo hacer reír a la gente.', filename='default.mp4', uploader_id=lyvion.id, channel_id=channel2.id)
        db.session.add(video1)
        db.session.add(video2)
        db.session.add(video3)
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)