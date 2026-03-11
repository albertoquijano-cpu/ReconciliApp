from sqlalchemy import create_engine, Column, String, Float, DateTime, Integer, Boolean, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os

# ── Conexión a la base de datos ───────────────────────────────
# Prioridad:
# 1. Variable de entorno DATABASE_URL (PostgreSQL en producción)
# 2. Variable de entorno RECONCILI_DB_PATH (SQLite en app empaquetada)
# 3. Ruta local por defecto (desarrollo)

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    # PostgreSQL — múltiples usuarios compartiendo datos
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    # SQLite — uso local
    if os.environ.get("RECONCILI_DB_PATH"):
        DB_PATH = os.environ["RECONCILI_DB_PATH"]
    else:
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        DB_PATH = os.path.join(BASE_DIR, "data", "reconciliapp.db")
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)

SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Periodo(Base):
    __tablename__ = "periodos"
    id = Column(Integer, primary_key=True, autoincrement=True)
    fecha_inicio = Column(DateTime, nullable=False)
    fecha_corte = Column(DateTime, nullable=False)
    descripcion = Column(String(200))
    creado_en = Column(DateTime, default=datetime.now)
    pedidos = relationship("Pedido", back_populates="periodo")
    pagos = relationship("PagoPlataforma", back_populates="periodo")

class Pedido(Base):
    __tablename__ = "pedidos"
    id = Column(Integer, primary_key=True, autoincrement=True)
    periodo_id = Column(Integer, ForeignKey("periodos.id"))
    numero_pedido = Column(String(50), nullable=False, index=True)
    cliente_nombre = Column(String(200))
    cliente_email = Column(String(200))
    fecha_pedido = Column(DateTime)
    valor_total = Column(Float, nullable=False)
    plataforma_pago = Column(String(50))
    estado_shopify = Column(String(50))
    estado_conciliacion = Column(String(50), default="pendiente")
    pago_id = Column(Integer, ForeignKey("pagos_plataforma.id"), nullable=True)
    fecha_pago_real = Column(DateTime, nullable=True)
    fecha_pago_esperada = Column(DateTime, nullable=True)
    dias_mora = Column(Integer, default=0)
    valor_recibido = Column(Float, nullable=True)
    comision_aplicada = Column(Float, nullable=True)
    es_pendiente_inicial = Column(Boolean, default=False)
    periodo = relationship("Periodo", back_populates="pedidos")
    pago = relationship("PagoPlataforma", back_populates="pedidos_asignados")

class PagoPlataforma(Base):
    __tablename__ = "pagos_plataforma"
    id = Column(Integer, primary_key=True, autoincrement=True)
    periodo_id = Column(Integer, ForeignKey("periodos.id"))
    plataforma = Column(String(50), nullable=False)
    fecha_pago = Column(DateTime, nullable=False)
    valor_neto = Column(Float, nullable=False)
    valor_bruto = Column(Float, nullable=True)
    comision_total = Column(Float, nullable=True)
    referencia = Column(String(200))
    descripcion = Column(Text)
    estado_asignacion = Column(String(50), default="sin_asignar")
    metodo_pago = Column(String(50))
    periodo = relationship("Periodo", back_populates="pagos")
    pedidos_asignados = relationship("Pedido", back_populates="pago")

class Credencial(Base):
    __tablename__ = "credenciales"
    id = Column(Integer, primary_key=True, autoincrement=True)
    plataforma = Column(String(50), unique=True, nullable=False)
    datos_cifrados = Column(Text, nullable=False)
    activa = Column(Boolean, default=True)
    ultima_sync = Column(DateTime, nullable=True)
    actualizada_en = Column(DateTime, default=datetime.now, onupdate=datetime.now)

def crear_tablas():
    Base.metadata.create_all(engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
