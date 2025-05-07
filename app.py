from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
import os
from werkzeug.security import generate_password_hash, check_password_hash
from supabase import create_client, Client
from datetime import datetime
import uuid

# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key-change-in-production')
csrf = CSRFProtect(app)

# Configuración de Supabase
supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_ANON_KEY')
supabase: Client = create_client(supabase_url, supabase_key)

# Rutas principales
@app.route('/')
def index():
    # Obtener películas destacadas
    response = supabase.table('movies').select('*').order('created_at', desc=True).limit(6).execute()
    movies = response.data
    return render_template('index.html', movies=movies)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Verificar credenciales con Supabase
        response = supabase.table('users').select('*').eq('email', email).execute()
        
        if response.data and check_password_hash(response.data[0]['password'], password):
            user = response.data[0]
            session['user_id'] = str(user['id'])  # Convertir UUID a string
            session['user_role'] = user['role']
            session['user_name'] = user['username']
            flash('Inicio de sesión exitoso', 'success')
            return redirect(url_for('index'))
        
        flash('Credenciales inválidas', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Verificar si el usuario ya existe
        response = supabase.table('users').select('*').eq('email', email).execute()
        
        if response.data:
            flash('El correo electrónico ya está registrado', 'error')
        else:
            # Crear nuevo usuario (por defecto como estándar)
            hashed_password = generate_password_hash(password)
            new_user = {
                'username': username,
                'email': email,
                'password': hashed_password,
                'role': 'standard'  # Por defecto, todos los usuarios son estándar
            }
            
            supabase.table('users').insert(new_user).execute()
            flash('Registro exitoso. Ahora puedes iniciar sesión', 'success')
            return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Has cerrado sesión', 'info')
    return redirect(url_for('index'))

@app.route('/movies')
def movies():
    # Obtener todas las películas
    response = supabase.table('movies').select('*').order('title').execute()
    movies = response.data
    return render_template('movies.html', movies=movies)

@app.route('/movie/<uuid:movie_id>')
def movie_detail(movie_id):
    # Convertir UUID a string para la consulta
    movie_id_str = str(movie_id)
    
    # Obtener detalles de la película
    movie_response = supabase.table('movies').select('*').eq('id', movie_id_str).execute()
    
    if not movie_response.data:
        flash('Película no encontrada', 'error')
        return redirect(url_for('movies'))
    
    movie = movie_response.data[0]
    
    # Obtener comentarios con información de usuario
    comments_response = supabase.table('comments').select('*, user:users(username)').eq('movie_id', movie_id_str).order('created_at', desc=True).execute()
    comments = comments_response.data
    
    # Obtener calificación promedio
    ratings_response = supabase.table('ratings').select('rating').eq('movie_id', movie_id_str).execute()
    ratings = ratings_response.data
    
    avg_rating = 0
    if ratings:
        avg_rating = sum(r['rating'] for r in ratings) / len(ratings)
    
    # Formatear fechas para los comentarios
    for comment in comments:
        if 'created_at' in comment and comment['created_at']:
            created_at = datetime.fromisoformat(comment['created_at'].replace('Z', '+00:00'))
            comment['created_at'] = created_at
    
    return render_template('movie_detail.html', movie=movie, comments=comments, avg_rating=avg_rating)

@app.route('/add_movie', methods=['GET', 'POST'])
def add_movie():
    # Verificar si el usuario es moderador
    if session.get('user_role') != 'moderator':
        flash('No tienes permisos para agregar películas', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        release_year = request.form.get('release_year')
        director = request.form.get('director')
        poster_url = request.form.get('poster_url')
        
        new_movie = {
            'title': title,
            'description': description,
            'release_year': int(release_year),
            'director': director,
            'poster_url': poster_url,
            'added_by': session.get('user_id')
        }
        
        supabase.table('movies').insert(new_movie).execute()
        flash('Película agregada exitosamente', 'success')
        return redirect(url_for('movies'))
    
    return render_template('add_movie.html')

@app.route('/add_comment/<uuid:movie_id>', methods=['POST'])
def add_comment(movie_id):
    if 'user_id' not in session:
        flash('Debes iniciar sesión para comentar', 'error')
        return redirect(url_for('login'))
    
    content = request.form.get('content')
    movie_id_str = str(movie_id)
    
    new_comment = {
        'movie_id': movie_id_str,
        'user_id': session.get('user_id'),
        'content': content
    }
    
    supabase.table('comments').insert(new_comment).execute()
    flash('Comentario agregado', 'success')
    return redirect(url_for('movie_detail', movie_id=movie_id))

@app.route('/rate_movie/<uuid:movie_id>', methods=['POST'])
def rate_movie(movie_id):
    if 'user_id' not in session:
        flash('Debes iniciar sesión para calificar', 'error')
        return redirect(url_for('login'))
    
    rating = int(request.form.get('rating'))
    user_id = session.get('user_id')
    movie_id_str = str(movie_id)
    
    # Verificar si el usuario ya calificó esta película
    response = supabase.table('ratings').select('*').eq('movie_id', movie_id_str).eq('user_id', user_id).execute()
    
    if response.data:
        # Actualizar calificación existente
        supabase.table('ratings').update({'rating': rating}).eq('movie_id', movie_id_str).eq('user_id', user_id).execute()
    else:
        # Crear nueva calificación
        new_rating = {
            'movie_id': movie_id_str,
            'user_id': user_id,
            'rating': rating
        }
        supabase.table('ratings').insert(new_rating).execute()
    
    flash('Calificación guardada', 'success')
    return redirect(url_for('movie_detail', movie_id=movie_id))

@app.template_filter('format_date')
def format_date(value, format='%d/%m/%Y %H:%M'):
    """Filtro para formatear fechas en las plantillas"""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return value
    return value.strftime(format)

if __name__ == '__main__':
    app.run(debug=True)