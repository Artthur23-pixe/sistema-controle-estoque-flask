import os
import base64
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, make_response, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from weasyprint import HTML, CSS
from collections import defaultdict
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

# --- Configuração ---
app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui_super_segura'
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'estoque.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

LIMITE_ESTOQUE_BAIXO = 1

# --- Configuração do Login ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Por favor, faça login para aceder a esta página."
login_manager.login_message_category = "danger"

# --- Fuso Horário Local ---
LOCAL_TIMEZONE = timezone(timedelta(hours=-3))
def get_local_time():
    return datetime.now(LOCAL_TIMEZONE)

# --- Modelos da Base de Dados ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='user')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User')
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.String(500), nullable=True)
    timestamp = db.Column(db.DateTime, default=get_local_time)

class Produto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), unique=True, nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    categoria = db.Column(db.String(100), nullable=True)
    descricao = db.Column(db.String(200), nullable=True)
    unidades = db.relationship('UnidadeProduto', backref='produto', lazy='dynamic')

class UnidadeProduto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    produto_id = db.Column(db.Integer, db.ForeignKey('produto.id'), nullable=False)
    pat = db.Column(db.String(100), unique=True, nullable=False)
    criado_em = db.Column(db.DateTime, default=get_local_time)

class Retirada(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    responsavel = db.Column(db.String(100), nullable=False)
    destino_geral = db.Column(db.String(200), nullable=False)
    chamado = db.Column(db.String(100), nullable=True)
    data_hora = db.Column(db.DateTime, default=get_local_time)
    status_distribuicao = db.Column(db.String(50), default='Pendente')
    itens = db.relationship('ItemRetirado', backref='retirada', lazy=True, cascade="all, delete-orphan")
    distribuicoes = db.relationship('Distribuicao', backref='retirada', lazy=True, cascade="all, delete-orphan")

class ItemRetirado(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    retirada_id = db.Column(db.Integer, db.ForeignKey('retirada.id'), nullable=False)
    produto_nome = db.Column(db.String(100), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)

class Distribuicao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    retirada_id = db.Column(db.Integer, db.ForeignKey('retirada.id'), nullable=False)
    produto_nome = db.Column(db.String(100), nullable=False)
    unidade_saude = db.Column(db.String(200), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    data_hora = db.Column(db.DateTime, default=get_local_time)

class Devolucao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    produto_nome = db.Column(db.String(100), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    responsavel = db.Column(db.String(100), nullable=False)
    origem = db.Column(db.String(200), nullable=False)
    data_hora = db.Column(db.DateTime, default=get_local_time)

class SolicitacaoCompra(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    produto_nome = db.Column(db.String(200), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    link_compra = db.Column(db.String(500), nullable=True)
    status = db.Column(db.String(50), default='Pendente')
    data_solicitacao = db.Column(db.DateTime, default=get_local_time)

# --- Funções Auxiliares ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def log_activity(action, details=""):
    if current_user.is_authenticated:
        log_entry = ActivityLog(user_id=current_user.id, action=action, details=details)
        db.session.add(log_entry)
        db.session.commit()

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash("Acesso restrito a administradores.", "danger")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

@app.context_processor
def inject_current_year():
    return {'current_year': datetime.utcnow().year}

def image_to_base64(image_path):
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except FileNotFoundError:
        return None

# --- Rotas de Autenticação ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            session.permanent = False
            log_activity("Login bem‑sucedido")
            return redirect(url_for('index'))
        else:
            flash('Nome de utilizador ou senha inválidos.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    log_activity("Logout")
    logout_user()
    return redirect(url_for('login'))

# --- Rotas Principais ---
@app.route('/')
@login_required
def index():
    categoria_selecionada = request.args.get('categoria', '')
    query_produtos = Produto.query
    if categoria_selecionada:
        query_produtos = query_produtos.filter(Produto.categoria == categoria_selecionada)
    inventario = query_produtos.order_by(Produto.nome).all()
    categorias_tuplas = db.session.query(Produto.categoria).distinct().order_by(Produto.categoria).all()
    categorias = [cat[0] for cat in categorias_tuplas if cat[0]]
    total_produtos_distintos = Produto.query.count()
    total_itens_estoque = db.session.query(func.sum(Produto.quantidade)).scalar() or 0
    produtos_estoque_baixo = Produto.query.filter(Produto.quantidade == LIMITE_ESTOQUE_BAIXO).all()
    return render_template('index.html',
                           inventario=inventario,
                           total_produtos_distintos=total_produtos_distintos,
                           total_itens_estoque=total_itens_estoque,
                           produtos_estoque_baixo=produtos_estoque_baixo,
                           categorias=categorias,
                           categoria_selecionada=categoria_selecionada,
                           limite_estoque_baixo=LIMITE_ESTOQUE_BAIXO)

# Rota Adicionar Produto
@app.route('/adicionar', methods=['GET', 'POST'])
@login_required
def adicionar_produto():
    if request.method == 'POST':
        nome = request.form['nome'].strip().title()
        quantidade = int(request.form['quantidade'])
        categoria = request.form['categoria'].strip().title()
        descricao = request.form['descricao'].strip()
        pats = request.form.getlist('pat[]')

        if quantidade <= 0:
            flash('Quantidade deve ser maior que zero.', 'danger')
            return redirect(url_for('adicionar_produto'))

        if len(pats) != quantidade:
            flash(f'O número de PATs ({len(pats)}) deve ser igual à quantidade informada ({quantidade}).', 'danger')
            return redirect(url_for('adicionar_produto'))

        if len(set(pats)) != len(pats):
            flash('Existem PATs repetidos no formulário. Todos devem ser únicos.', 'danger')
            return redirect(url_for('adicionar_produto'))

        existente = UnidadeProduto.query.filter(UnidadeProduto.pat.in_(pats)).first()
        if existente:
            flash(f'O PAT "{existente.pat}" já está cadastrado para o produto "{existente.produto.nome}".', 'danger')
            return redirect(url_for('adicionar_produto'))

        produto = Produto.query.filter_by(nome=nome).first()
        if produto:
            produto.quantidade += quantidade
            log_activity("Atualização de Produto", f"Adicionou {quantidade}x {nome}")
        else:
            produto = Produto(nome=nome, quantidade=quantidade, categoria=categoria, descricao=descricao)
            db.session.add(produto)
            db.session.flush()  # garante produto.id
            log_activity("Criação de Produto", f"Criou {quantidade}x {nome}")

        for pat in pats:
            unidade = UnidadeProduto(produto_id=produto.id, pat=pat)
            db.session.add(unidade)

        db.session.commit()
        flash(f'Produto "{nome}" salvo com sucesso com {quantidade} unidade(s) e PATs informados.', 'success')
        return redirect(url_for('index'))

    return render_template('adicionar_produto.html')

# Rota Editar Produto
@app.route('/editar/<int:produto_id>', methods=['GET', 'POST'])
@login_required
def editar_produto(produto_id):
    produto = Produto.query.get_or_404(produto_id)
    unidades_existentes = produto.unidades.count()

    if request.method == 'POST':
        novo_nome = request.form['nome'].strip().title()
        nova_quantidade = int(request.form['quantidade'])
        nova_categoria = request.form['categoria'].strip().title()
        nova_descricao = request.form['descricao'].strip()
        novos_pats = request.form.getlist('pat[]')

        if nova_quantidade < unidades_existentes:
            flash(f'A nova quantidade ({nova_quantidade}) não pode ser menor que a quantidade atual ({unidades_existentes}).', 'danger')
            return redirect(url_for('editar_produto', produto_id=produto.id))

        dif = nova_quantidade - unidades_existentes
        if dif > 0:
            if len(novos_pats) != dif:
                flash(f'Deve informar {dif} novo(s) PAT(s), mas foram informados {len(novos_pats)}.', 'danger')
                return redirect(url_for('editar_produto', produto_id=produto.id))

            if len(set(novos_pats)) != len(novos_pats):
                flash('Existem PATs repetidos no formulário. Todos devem ser únicos.', 'danger')
                return redirect(url_for('editar_produto', produto_id=produto.id))

            existente = UnidadeProduto.query.filter(UnidadeProduto.pat.in_(novos_pats)).first()
            if existente:
                flash(f'O PAT "{existente.pat}" já está cadastrado (Produto: {existente.produto.nome}).', 'danger')
                return redirect(url_for('editar_produto', produto_id=produto.id))

            for pat in novos_pats:
                unidade = UnidadeProduto(produto_id=produto.id, pat=pat)
                db.session.add(unidade)

        produto.nome = novo_nome
        produto.quantidade = nova_quantidade
        produto.categoria = nova_categoria
        produto.descricao = nova_descricao

        log_activity("Edição de Produto", f"Editou {produto.nome}, nova quantidade: {nova_quantidade}")

        db.session.commit()
        flash('Produto atualizado com sucesso!', 'success')
        return redirect(url_for('index'))

    return render_template('editar_produto.html', produto=produto, unidades_existentes=unidades_existentes)

# Outras rotas permanecem iguais ao seu código original (retirada, devolução, distribuição, históricos, relatórios…)

@app.route('/retirada', methods=['GET', 'POST'])
@login_required
def retirada_equipamento():
    if request.method == 'POST':
        destino_geral = request.form['destino'].strip()
        chamado = request.form['chamado'].strip()
        nova_retirada = Retirada(responsavel=current_user.username, destino_geral=destino_geral, chamado=chamado)
        db.session.add(nova_retirada)
        produtos_ids = request.form.getlist('produto_id[]')
        quantidades = request.form.getlist('quantidade[]')
        itens_log = []
        for produto_id, quantidade_str in zip(produtos_ids, quantidades):
            if not produto_id or not quantidade_str:
                continue
            produto = Produto.query.get_or_404(int(produto_id))
            quantidade = int(quantidade_str)
            if quantidade > 0 and quantidade <= produto.quantidade:
                produto.quantidade -= quantidade
                item_retirado = ItemRetirado(retirada=nova_retirada, produto_nome=produto.nome, quantidade=quantidade)
                db.session.add(item_retirado)
                itens_log.append(f"{quantidade}x {produto.nome}")
            else:
                flash(f'Quantidade inválida ou insuficiente para {produto.nome}.', 'danger')
                db.session.rollback()
                return redirect(url_for('retirada_equipamento'))
        log_activity("Retirada de Material", f"Itens: {', '.join(itens_log)} para {destino_geral}")
        db.session.commit()
        return redirect(url_for('retirada_sucesso', retirada_id=nova_retirada.id))
    produtos = Produto.query.order_by(Produto.nome).all()
    return render_template('retirada_equipamento.html', produtos=produtos)

# ... (adicione as demais rotas conforme seu original) ...

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not User.query.first():
            users_data = {
                'Kauê Arthur': 'admin',
                'Eudes José': 'user',
                'Marcos Aurélio': 'user',
                'Lucas Casemiro': 'user',
                'Wallisson Cavalcanti': 'admin'
            }
            password = 'P@ssw0rd'
            for user_name, role in users_data.items():
                new_user = User(username=user_name, role=role)
                new_user.set_password(password)
                db.session.add(new_user)
            db.session.commit()
            print("Utilizadores iniciais com perfis criados com sucesso!")
    app.run(debug=True, host='0.0.0.0')
