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
            log_activity("Login bem-sucedido")
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
    return render_template('index.html', inventario=inventario, total_produtos_distintos=total_produtos_distintos, total_itens_estoque=total_itens_estoque, produtos_estoque_baixo=produtos_estoque_baixo, categorias=categorias, categoria_selecionada=categoria_selecionada, limite_estoque_baixo=LIMITE_ESTOQUE_BAIXO)

@app.route('/adicionar', methods=['GET', 'POST'])
@login_required
def adicionar_produto():
    if request.method == 'POST':
        nome = request.form['nome'].strip().title(); quantidade = int(request.form['quantidade']); categoria = request.form['categoria'].strip().title(); descricao = request.form['descricao'].strip()
        produto_existente = Produto.query.filter_by(nome=nome).first()
        if produto_existente:
            produto_existente.quantidade += quantidade; produto_existente.categoria = categoria; produto_existente.descricao = descricao
            log_activity("Atualização de Produto", f"Adicionou {quantidade}x {nome}")
        else:
            novo_produto = Produto(nome=nome, quantidade=quantidade, categoria=categoria, descricao=descricao); db.session.add(novo_produto)
            log_activity("Criação de Produto", f"Criou {quantidade}x {nome}")
        db.session.commit()
        flash(f'Produto "{nome}" salvo com sucesso!', 'success'); return redirect(url_for('index'))
    return render_template('adicionar_produto.html')
    
@app.route('/retirada', methods=['GET', 'POST'])
@login_required
def retirada_equipamento():
    if request.method == 'POST':
        destino_geral = request.form['destino'].strip(); chamado = request.form['chamado'].strip()
        nova_retirada = Retirada(responsavel=current_user.username, destino_geral=destino_geral, chamado=chamado)
        db.session.add(nova_retirada)
        produtos_ids = request.form.getlist('produto_id[]')
        quantidades = request.form.getlist('quantidade[]')
        itens_log = []
        for produto_id, quantidade_str in zip(produtos_ids, quantidades):
            if not produto_id or not quantidade_str: continue
            produto = Produto.query.get_or_404(produto_id)
            quantidade = int(quantidade_str)
            if quantidade > 0 and quantidade <= produto.quantidade:
                produto.quantidade -= quantidade
                item_retirado = ItemRetirado(retirada=nova_retirada, produto_nome=produto.nome, quantidade=quantidade)
                db.session.add(item_retirado)
                itens_log.append(f"{quantidade}x {produto.nome}")
            else:
                flash(f'Quantidade inválida ou insuficiente para {produto.nome}.', 'danger'); db.session.rollback(); return redirect(url_for('retirada_equipamento'))
        log_activity("Retirada de Material", f"Itens: {', '.join(itens_log)} para {destino_geral}")
        db.session.commit()
        return redirect(url_for('retirada_sucesso', retirada_id=nova_retirada.id))
    produtos = Produto.query.order_by(Produto.nome).all()
    return render_template('retirada_equipamento.html', produtos=produtos)

@app.route('/retirada_sucesso/<int:retirada_id>')
@login_required
def retirada_sucesso(retirada_id):
    retirada = Retirada.query.get_or_404(retirada_id)
    return render_template('retirada_sucesso.html', retirada=retirada)

@app.route('/termo_recebimento/<int:retirada_id>')
@login_required
def termo_recebimento_pdf(retirada_id):
    retirada = Retirada.query.get_or_404(retirada_id)
    header_image_path = os.path.join(basedir, 'novetech_header.png')
    header_image_b64 = image_to_base64(header_image_path)
    rendered_html = render_template('termo.html', retirada=retirada, header_image=header_image_b64)
    pdf = HTML(string=rendered_html).write_pdf()
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename=termo_retirada_{retirada.id}.pdf'
    return response

@app.route('/distribuicao', methods=['GET', 'POST'])
@login_required
def distribuicao_equipamento():
    if request.method == 'POST':
        retirada_id = request.form.get('retirada_id'); retirada = Retirada.query.get_or_404(retirada_id)
        itens_retirados_map = {item.produto_nome: item.quantidade for item in retirada.itens}
        distribuicao_total_map = defaultdict(int)
        unidades = request.form.getlist('unidade_saude[]'); produtos_distribuidos = request.form.getlist('produto_distribuido[]'); quantidades_distribuidas = request.form.getlist('quantidade_distribuida[]')
        for produto, qtd_str in zip(produtos_distribuidos, quantidades_distribuidas):
            if produto and qtd_str and int(qtd_str) > 0: distribuicao_total_map[produto] += int(qtd_str)
        produtos_devolvidos = request.form.getlist('produto_devolvido[]'); quantidades_devolvidas = request.form.getlist('quantidade_devolvida[]')
        for produto, qtd_str in zip(produtos_devolvidos, quantidades_devolvidas):
            if produto and qtd_str and int(qtd_str) > 0: distribuicao_total_map[produto] += int(qtd_str)
        for produto_nome, total_distribuido in distribuicao_total_map.items():
            if total_distribuido > itens_retirados_map.get(produto_nome, 0):
                flash(f'Erro: Total de "{produto_nome}" ({total_distribuido}) excede a quantidade retirada ({itens_retirados_map.get(produto_nome, 0)}).', 'danger'); return redirect(url_for('distribuicao_equipamento'))
        
        log_details = []
        for unidade, produto_nome, qtd_str in zip(unidades, produtos_distribuidos, quantidades_distribuidas):
            if unidade and produto_nome and qtd_str and int(qtd_str) > 0:
                dist = Distribuicao(retirada_id=retirada_id, produto_nome=produto_nome, unidade_saude=unidade, quantidade=int(qtd_str)); db.session.add(dist)
                log_details.append(f"{qtd_str}x {produto_nome} para {unidade}")
        for produto_nome, qtd_str in zip(produtos_devolvidos, quantidades_devolvidas):
            if produto_nome and qtd_str and int(qtd_str) > 0:
                produto_db = Produto.query.filter_by(nome=produto_nome).first()
                if produto_db:
                    produto_db.quantidade += int(qtd_str)
                    dev = Devolucao(produto_nome=produto_nome, quantidade=int(qtd_str), responsavel=current_user.username, origem=f"Sobra da Retirada #{retirada.id}"); db.session.add(dev)
                    log_details.append(f"{qtd_str}x {produto_nome} devolvido")
        
        log_activity("Distribuição", f"Ref. Retirada #{retirada_id}: {', '.join(log_details)}")
        retirada.status_distribuicao = 'Concluído'
        db.session.commit()
        flash('Distribuição registada com sucesso!', 'success'); return redirect(url_for('index'))
    retiradas_pendentes = Retirada.query.filter_by(status_distribuicao='Pendente').order_by(Retirada.data_hora.desc()).all()
    return render_template('distribuicao_equipamento.html', retiradas_pendentes=retiradas_pendentes)

@app.route('/get_itens_retirada/<int:retirada_id>')
@login_required
def get_itens_retirada(retirada_id):
    retirada = Retirada.query.get_or_404(retirada_id)
    itens = [{'produto_nome': item.produto_nome, 'quantidade': item.quantidade} for item in retirada.itens]
    return jsonify(itens)

@app.route('/devolucao', methods=['GET', 'POST'])
@login_required
def devolucao_equipamento():
    if request.method == 'POST':
        origem = request.form['origem'].strip()
        produtos_ids = request.form.getlist('produto_id[]')
        quantidades = request.form.getlist('quantidade[]')
        log_details = []
        for produto_id, quantidade_str in zip(produtos_ids, quantidades):
            if not produto_id or not quantidade_str: continue
            quantidade_devolvida = int(quantidade_str); produto = Produto.query.get_or_404(produto_id)
            if quantidade_devolvida > 0:
                produto.quantidade += quantidade_devolvida
                nova_devolucao = Devolucao(produto_nome=produto.nome, quantidade=quantidade_devolvida, responsavel=current_user.username, origem=origem)
                db.session.add(nova_devolucao)
                log_details.append(f"{quantidade_devolvida}x {produto.nome} de {origem}")
        log_activity("Devolução Direta", ", ".join(log_details))
        db.session.commit()
        flash('Devolução direta registada com sucesso!', 'success'); return redirect(url_for('index'))
    produtos = Produto.query.order_by(Produto.nome).all()
    return render_template('devolucao_equipamento.html', produtos=produtos)

@app.route('/historico_retiradas')
@login_required
def visualizar_historico_retiradas():
    page = request.args.get('page', 1, type=int)
    query = Retirada.query
    search_terms = {k: v for k, v in request.args.items() if k != 'page' and v}
    if search_terms.get('responsavel'): query = query.filter(Retirada.responsavel.ilike(f"%{search_terms['responsavel']}%"))
    if search_terms.get('destino'): query = query.filter(Retirada.destino_geral.ilike(f"%{search_terms['destino']}%"))
    if search_terms.get('data'):
        try: data_filtro = datetime.strptime(search_terms['data'], '%Y-%m-%d').date(); query = query.filter(func.date(Retirada.data_hora) == data_filtro)
        except ValueError: flash('Formato de data inválido.', 'danger')
    retiradas_paginadas = query.order_by(Retirada.data_hora.desc()).paginate(page=page, per_page=10, error_out=False)
    return render_template('historico_retiradas.html', retiradas_paginadas=retiradas_paginadas, search_terms=search_terms)
    
@app.route('/editar/<int:produto_id>', methods=['GET', 'POST'])
@login_required
def editar_produto(produto_id):
    produto = Produto.query.get_or_404(produto_id)
    if request.method == 'POST':
        produto.nome = request.form['nome'].strip().title(); produto.quantidade = int(request.form['quantidade']); produto.categoria = request.form['categoria'].strip().title(); produto.descricao = request.form['descricao'].strip()
        log_activity("Edição de Produto", f"Editou {produto.nome}")
        db.session.commit()
        flash('Produto atualizado com sucesso!', 'success'); return redirect(url_for('index'))
    return render_template('editar_produto.html', produto=produto)

@app.route('/excluir/<int:produto_id>', methods=['POST'])
@login_required
@admin_required
def excluir_produto(produto_id):
    produto = Produto.query.get_or_404(produto_id)
    log_activity("Exclusão de Produto", f"Excluiu {produto.nome}")
    db.session.delete(produto)
    db.session.commit()
    flash(f'Produto "{produto.nome}" excluído com sucesso!', 'success'); return redirect(url_for('index'))

@app.route('/historico_devolucoes')
@login_required
def visualizar_historico_devolucoes():
    page = request.args.get('page', 1, type=int)
    query = Devolucao.query
    search_terms = {k: v for k, v in request.args.items() if k != 'page' and v}
    if search_terms.get('produto'): query = query.filter(Devolucao.produto_nome.ilike(f"%{search_terms['produto']}%"))
    if search_terms.get('responsavel'): query = query.filter(Devolucao.responsavel.ilike(f"%{search_terms['responsavel']}%"))
    if search_terms.get('origem'): query = query.filter(Devolucao.origem.ilike(f"%{search_terms['origem']}%"))
    if search_terms.get('data'):
        try: data_filtro = datetime.strptime(search_terms['data'], '%Y-%m-%d').date(); query = query.filter(func.date(Devolucao.data_hora) == data_filtro)
        except ValueError: flash('Formato de data inválido.', 'danger')
    devolucoes_paginadas = query.order_by(Devolucao.data_hora.desc()).paginate(page=page, per_page=10, error_out=False)
    return render_template('historico_devolucoes.html', devolucoes_paginadas=devolucoes_paginadas, search_terms=search_terms)

@app.route('/historico_distribuicao')
@login_required
def visualizar_historico_distribuicao():
    page = request.args.get('page', 1, type=int)
    query = Distribuicao.query
    search_terms = {k: v for k, v in request.args.items() if k != 'page' and v}
    if search_terms.get('unidade'): query = query.filter(Distribuicao.unidade_saude.ilike(f"%{search_terms['unidade']}%"))
    if search_terms.get('produto'): query = query.filter(Distribuicao.produto_nome.ilike(f"%{search_terms['produto']}%"))
    if search_terms.get('responsavel'): query = query.join(Retirada).filter(Retirada.responsavel.ilike(f"%{search_terms['responsavel']}%"))
    if search_terms.get('data'):
        try: data_filtro = datetime.strptime(search_terms['data'], '%Y-%m-%d').date(); query = query.filter(func.date(Distribuicao.data_hora) == data_filtro)
        except ValueError: flash('Formato de data inválido.', 'danger')
    distribuicoes_paginadas = query.order_by(Distribuicao.data_hora.desc()).paginate(page=page, per_page=10, error_out=False)
    return render_template('historico_distribuicao.html', distribuicoes_paginadas=distribuicoes_paginadas, search_terms=search_terms)

@app.route('/solicitacao_compra', methods=['GET', 'POST'])
@login_required
def solicitacao_compra():
    if request.method == 'POST':
        produtos = request.form.getlist('produto_nome[]'); quantidades = request.form.getlist('quantidade[]'); links = request.form.getlist('link_compra[]')
        log_details = []
        for nome, qtd, link in zip(produtos, quantidades, links):
            if nome and qtd and int(qtd) > 0:
                nova_solicitacao = SolicitacaoCompra(produto_nome=nome.strip(), quantidade=int(qtd), link_compra=link.strip())
                db.session.add(nova_solicitacao)
                log_details.append(f"{qtd}x {nome}")
        log_activity("Solicitação de Compra", ", ".join(log_details))
        db.session.commit()
        flash('Solicitação de compra registada com sucesso!', 'success')
        return redirect(url_for('solicitacao_compra'))
    solicitacoes_pendentes = SolicitacaoCompra.query.filter_by(status='Pendente').order_by(SolicitacaoCompra.data_solicitacao.desc()).all()
    return render_template('solicitacao_compra.html', solicitacoes=solicitacoes_pendentes)

@app.route('/solicitacao_compra/marcar_comprado/<int:item_id>', methods=['POST'])
@login_required
@admin_required
def marcar_comprado(item_id):
    item = SolicitacaoCompra.query.get_or_404(item_id)
    item.status = 'Comprado'
    log_activity("Marcação de Compra", f"Marcou '{item.produto_nome}' como comprado")
    db.session.commit()
    flash(f'Item "{item.produto_nome}" marcado como comprado.', 'success')
    return redirect(url_for('solicitacao_compra'))

@app.route('/solicitacao_compra/excluir/<int:item_id>', methods=['POST'])
@login_required
def excluir_solicitacao(item_id):
    item = SolicitacaoCompra.query.get_or_404(item_id)
    log_activity("Exclusão de Solicitação", f"Excluiu solicitação de '{item.produto_nome}'")
    db.session.delete(item)
    db.session.commit()
    flash(f'Item "{item.produto_nome}" removido da lista.', 'success')
    return redirect(url_for('solicitacao_compra'))

@app.route('/relatorio_devolucoes_pdf')
@login_required
def relatorio_devolucoes_pdf():
    query = Devolucao.query; search_terms = {k: v for k, v in request.args.items() if v}
    devolucoes = query.order_by(Devolucao.data_hora.desc()).all()
    header_image_path = os.path.join(basedir, 'novetech_header.png'); header_image_b64 = image_to_base64(header_image_path)
    rendered_html = render_template('relatorio_devolucoes.html', devolucoes=devolucoes, header_image=header_image_b64, search_terms=search_terms, data_emissao=get_local_time())
    pdf = HTML(string=rendered_html).write_pdf(); response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'; response.headers['Content-Disposition'] = 'inline; filename=relatorio_devolucoes.pdf'
    return response

@app.route('/relatorio_distribuicao_pdf')
@login_required
def relatorio_distribuicao_pdf():
    query = Distribuicao.query; search_terms = {k: v for k, v in request.args.items() if v}
    distribuicoes = query.order_by(Distribuicao.data_hora.desc()).all()
    header_image_path = os.path.join(basedir, 'novetech_header.png'); header_image_b64 = image_to_base64(header_image_path)
    rendered_html = render_template('relatorio_distribuicao.html', distribuicoes=distribuicoes, header_image=header_image_b64, search_terms=search_terms, data_emissao=get_local_time())
    pdf = HTML(string=rendered_html).write_pdf(); response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'; response.headers['Content-Disposition'] = 'inline; filename=relatorio_distribuicao.pdf'
    return response

@app.route('/relatorio_solicitacao_pdf')
@login_required
def relatorio_solicitacao_pdf():
    solicitacoes = SolicitacaoCompra.query.filter_by(status='Pendente').order_by(SolicitacaoCompra.produto_nome).all()
    header_image_path = os.path.join(basedir, 'novetech_header.png')
    header_image_b64 = image_to_base64(header_image_path)
    rendered_html = render_template('relatorio_solicitacao.html', solicitacoes=solicitacoes, header_image=header_image_b64, data_emissao=get_local_time())
    pdf = HTML(string=rendered_html).write_pdf()
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'inline; filename=relatorio_solicitacao_compra.pdf'
    return response

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    users = User.query.order_by(User.username).all()
    return render_template('admin_dashboard.html', users=users)

@app.route('/admin/activity_log/<int:user_id>')
@login_required
@admin_required
def user_activity_log(user_id):
    user = User.query.get_or_404(user_id)
    page = request.args.get('page', 1, type=int)
    logs = ActivityLog.query.filter_by(user_id=user.id).order_by(ActivityLog.timestamp.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('user_activity_log.html', user=user, logs_paginados=logs)

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