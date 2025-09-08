import os
import base64
from datetime import datetime, timezone, timedelta # Importações atualizadas
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, make_response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from weasyprint import HTML, CSS
from collections import defaultdict

# --- Configuração ---
app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui'
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'estoque.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
LIMITE_ESTOQUE_BAIXO = 1

# --- FUSO HORÁRIO LOCAL (GMT-3) ---
LOCAL_TIMEZONE = timezone(timedelta(hours=-3))
def get_local_time():
    return datetime.now(LOCAL_TIMEZONE)

# --- Modelos da Base de Dados (com hora local) ---
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
    data_hora = db.Column(db.DateTime, default=get_local_time) # ATUALIZADO
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
    data_hora = db.Column(db.DateTime, default=get_local_time) # ATUALIZADO

class Devolucao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    produto_nome = db.Column(db.String(100), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    responsavel = db.Column(db.String(100), nullable=False)
    origem = db.Column(db.String(200), nullable=False)
    data_hora = db.Column(db.DateTime, default=get_local_time) # ATUALIZADO

@app.context_processor
def inject_current_year():
    return {'current_year': datetime.utcnow().year}

def image_to_base64(image_path):
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except FileNotFoundError:
        return None

# --- Rotas Principais ---
@app.route('/')
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
def adicionar_produto():
    if request.method == 'POST':
        nome = request.form['nome'].strip().title(); quantidade = int(request.form['quantidade']); categoria = request.form['categoria'].strip().title(); descricao = request.form['descricao'].strip()
        produto_existente = Produto.query.filter_by(nome=nome).first()
        if produto_existente:
            produto_existente.quantidade += quantidade; produto_existente.categoria = categoria; produto_existente.descricao = descricao
        else:
            novo_produto = Produto(nome=nome, quantidade=quantidade, categoria=categoria, descricao=descricao); db.session.add(novo_produto)
        db.session.commit()
        flash(f'Produto "{nome}" salvo com sucesso!', 'success'); return redirect(url_for('index'))
    return render_template('adicionar_produto.html')
    
@app.route('/retirada', methods=['GET', 'POST'])
def retirada_equipamento():
    if request.method == 'POST':
        responsavel = request.form['responsavel'].strip().title(); destino_geral = request.form['destino'].strip(); chamado = request.form['chamado'].strip()
        nova_retirada = Retirada(responsavel=responsavel, destino_geral=destino_geral, chamado=chamado)
        db.session.add(nova_retirada)
        produtos_ids = request.form.getlist('produto_id[]')
        quantidades = request.form.getlist('quantidade[]')
        for produto_id, quantidade_str in zip(produtos_ids, quantidades):
            if not produto_id or not quantidade_str: continue
            produto = Produto.query.get_or_404(produto_id)
            quantidade = int(quantidade_str)
            if quantidade > 0 and quantidade <= produto.quantidade:
                produto.quantidade -= quantidade
                item_retirado = ItemRetirado(retirada=nova_retirada, produto_nome=produto.nome, quantidade=quantidade)
                db.session.add(item_retirado)
            else:
                flash(f'Quantidade inválida ou insuficiente para {produto.nome}.', 'danger'); db.session.rollback(); return redirect(url_for('retirada_equipamento'))
        db.session.commit()
        return redirect(url_for('retirada_sucesso', retirada_id=nova_retirada.id))
    produtos = Produto.query.order_by(Produto.nome).all()
    return render_template('retirada_equipamento.html', produtos=produtos)

@app.route('/retirada_sucesso/<int:retirada_id>')
def retirada_sucesso(retirada_id):
    retirada = Retirada.query.get_or_404(retirada_id)
    return render_template('retirada_sucesso.html', retirada=retirada)

@app.route('/termo_recebimento/<int:retirada_id>')
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
        for unidade, produto_nome, qtd_str in zip(unidades, produtos_distribuidos, quantidades_distribuidas):
            if unidade and produto_nome and qtd_str and int(qtd_str) > 0:
                dist = Distribuicao(retirada_id=retirada_id, produto_nome=produto_nome, unidade_saude=unidade, quantidade=int(qtd_str)); db.session.add(dist)
        for produto_nome, qtd_str in zip(produtos_devolvidos, quantidades_devolvidas):
            if produto_nome and qtd_str and int(qtd_str) > 0:
                produto_db = Produto.query.filter_by(nome=produto_nome).first()
                if produto_db:
                    produto_db.quantidade += int(qtd_str)
                    dev = Devolucao(produto_nome=produto_nome, quantidade=int(qtd_str), responsavel=retirada.responsavel, origem=f"Sobra da Retirada #{retirada.id}"); db.session.add(dev)
        retirada.status_distribuicao = 'Concluído'
        db.session.commit()
        flash('Distribuição registada com sucesso!', 'success'); return redirect(url_for('index'))
    retiradas_pendentes = Retirada.query.filter_by(status_distribuicao='Pendente').order_by(Retirada.data_hora.desc()).all()
    return render_template('distribuicao_equipamento.html', retiradas_pendentes=retiradas_pendentes)

@app.route('/get_itens_retirada/<int:retirada_id>')
def get_itens_retirada(retirada_id):
    retirada = Retirada.query.get_or_404(retirada_id)
    itens = [{'produto_nome': item.produto_nome, 'quantidade': item.quantidade} for item in retirada.itens]
    return jsonify(itens)

@app.route('/devolucao', methods=['GET', 'POST'])
def devolucao_equipamento():
    if request.method == 'POST':
        responsavel = request.form['responsavel'].strip().title(); origem = request.form['origem'].strip()
        produtos_ids = request.form.getlist('produto_id[]'); quantidades = request.form.getlist('quantidade[]')
        for produto_id, quantidade_str in zip(produtos_ids, quantidades):
            if not produto_id or not quantidade_str: continue
            quantidade_devolvida = int(quantidade_str); produto = Produto.query.get_or_404(produto_id)
            if quantidade_devolvida > 0:
                produto.quantidade += quantidade_devolvida
                nova_devolucao = Devolucao(produto_nome=produto.nome, quantidade=quantidade_devolvida, responsavel=responsavel, origem=origem)
                db.session.add(nova_devolucao)
        db.session.commit()
        flash('Devolução direta registada com sucesso!', 'success'); return redirect(url_for('index'))
    produtos = Produto.query.order_by(Produto.nome).all()
    return render_template('devolucao_equipamento.html', produtos=produtos)

@app.route('/historico_retiradas')
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
def editar_produto(produto_id):
    produto = Produto.query.get_or_404(produto_id)
    if request.method == 'POST':
        produto.nome = request.form['nome'].strip().title(); produto.quantidade = int(request.form['quantidade']); produto.categoria = request.form['categoria'].strip().title(); produto.descricao = request.form['descricao'].strip()
        db.session.commit()
        flash('Produto atualizado com sucesso!', 'success'); return redirect(url_for('index'))
    return render_template('editar_produto.html', produto=produto)

@app.route('/excluir/<int:produto_id>', methods=['POST'])
def excluir_produto(produto_id):
    produto = Produto.query.get_or_404(produto_id)
    db.session.delete(produto)
    db.session.commit()
    flash(f'Produto "{produto.nome}" excluído com sucesso!', 'success'); return redirect(url_for('index'))

@app.route('/historico_devolucoes')
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

@app.route('/relatorio_devolucoes_pdf')
def relatorio_devolucoes_pdf():
    query = Devolucao.query
    search_terms = {k: v for k, v in request.args.items() if v}
    if search_terms.get('produto'): query = query.filter(Devolucao.produto_nome.ilike(f"%{search_terms['produto']}%"))
    if search_terms.get('responsavel'): query = query.filter(Devolucao.responsavel.ilike(f"%{search_terms['responsavel']}%"))
    if search_terms.get('origem'): query = query.filter(Devolucao.origem.ilike(f"%{search_terms['origem']}%"))
    if search_terms.get('data'):
        try: data_filtro = datetime.strptime(search_terms['data'], '%Y-%m-%d').date(); query = query.filter(func.date(Devolucao.data_hora) == data_filtro)
        except ValueError: pass
    devolucoes = query.order_by(Devolucao.data_hora.desc()).all()
    header_image_path = os.path.join(basedir, 'novetech_header.png')
    header_image_b64 = image_to_base64(header_image_path)
    rendered_html = render_template('relatorio_devolucoes.html', devolucoes=devolucoes, header_image=header_image_b64, search_terms=search_terms, data_emissao=get_local_time()) # ATUALIZADO
    pdf = HTML(string=rendered_html).write_pdf()
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'inline; filename=relatorio_devolucoes.pdf'
    return response

@app.route('/relatorio_distribuicao_pdf')
def relatorio_distribuicao_pdf():
    query = Distribuicao.query
    search_terms = {k: v for k, v in request.args.items() if v}
    if search_terms.get('unidade'): query = query.filter(Distribuicao.unidade_saude.ilike(f"%{search_terms['unidade']}%"))
    if search_terms.get('produto'): query = query.filter(Distribuicao.produto_nome.ilike(f"%{search_terms['produto']}%"))
    if search_terms.get('responsavel'): query = query.join(Retirada).filter(Retirada.responsavel.ilike(f"%{search_terms['responsavel']}%"))
    if search_terms.get('data'):
        try: data_filtro = datetime.strptime(search_terms['data'], '%Y-%m-%d').date(); query = query.filter(func.date(Distribuicao.data_hora) == data_filtro)
        except ValueError: pass
    distribuicoes = query.order_by(Distribuicao.data_hora.desc()).all()
    header_image_path = os.path.join(basedir, 'novetech_header.png')
    header_image_b64 = image_to_base64(header_image_path)
    rendered_html = render_template('relatorio_distribuicao.html', distribuicoes=distribuicoes, header_image=header_image_b64, search_terms=search_terms, data_emissao=get_local_time()) # ATUALIZADO
    pdf = HTML(string=rendered_html).write_pdf()
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'inline; filename=relatorio_distribuicao.pdf'
    return response

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0')