from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pymongo import MongoClient
from passlib.hash import bcrypt
from datetime import datetime
import io
from garbage_classifier import classify_image_from_stream

#mongodb://localhost:27017/
#Jaco:505

# ================== Conexión a Mongo ===================
client = MongoClient(
    # "mongodb://localhost:27017/"  # Cambia esto si tu MongoDB está en otro host/puerto
    "mongodb+srv://Jaco:505@reciclajedb.tvx4n5b.mongodb.net/?retryWrites=true&w=majority&appName=ReciclajeDB"
)
db = client["reciclaje"]

# ================== App & CORS =========================
app = FastAPI(title="EcoRecycle API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://192.168.20.23:5500",
        "http://10.0.2.2:5500",
        "http://127.0.0.1:5501",   # <— tu front actual
        "http://localhost:5501",
        "http://192.168.20.23:5501",
        "http://10.0.2.2:5500",
        "127.0.0.1:52731",
        "https://greenscanner.vercel.app/",
    ],
    allow_credentials=True,  # pon False si no usas cookies/sesiones
    allow_methods=["*"],
    allow_headers=["*"],
)


# ================== Modelos ============================
class User(BaseModel):
    nombre: str
    correo: str
    password: str

class Login(BaseModel):
    correo: str
    password: str

class Puntos(BaseModel):
    correo: str
    puntos: int

class Canje(BaseModel):
    correo: str
    premio: str


# ================== Utils ==============================
def get_user(correo: str):
    return db.usuarios.find_one({"correo": correo})

def int_or_0(x, key: str):
    try:
        return int(x.get(key, 0))
    except Exception:
        return 0


# ================== Rutas ==============================
@app.get("/")
def root():
    return {"status": "ok", "service": "EcoRecycle API"}


# -------- Puntos (saldo actual) ------------------------
@app.get("/usuarios/{correo}/puntos")
def puntos_usuario(correo: str):
    u = get_user(correo)
    if not u:
        return {"error": "Usuario no encontrado"}
    return {"correo": correo, "puntos": int_or_0(u, "puntos")}


# -------- Puntos acumulados (de por vida) --------------
@app.get("/usuarios/{correo}/puntos-acumulados")
def puntos_acumulados_usuario(correo: str):
    u = get_user(correo)
    if not u:
        return {"error": "Usuario no encontrado"}
    return {"correo": correo, "puntos_acumulados": int_or_0(u, "puntos_acumulados")}


# -------- Login ----------------------------------------
@app.post("/login")
def login(user: Login):
    db_user = get_user(user.correo)
    if not db_user or not bcrypt.verify(user.password, db_user["password"]):
        return {"error": "Credenciales incorrectas"}
    return {
        "mensaje": "Login exitoso",
        "puntos": int_or_0(db_user, "puntos"),
        "puntos_acumulados": int_or_0(db_user, "puntos_acumulados"),
    }


# -------- Registro -------------------------------------
@app.post("/register")
def register(user: User):
    if get_user(user.correo):
        return {"error": "Usuario ya registrado"}
    hashed = bcrypt.hash(user.password)
    db.usuarios.insert_one(
        {
            "nombre": user.nombre,
            "correo": user.correo,
            "password": hashed,
            "puntos": 0,                # saldo actual
            "puntos_acumulados": 0,     # acumulado de por vida
        }
    )
    return {"mensaje": "Usuario registrado"}


# -------- Sumar puntos (escáner / voz) -----------------
@app.post("/puntos/agregar")
def agregar_puntos(puntos: Puntos):
    # Suma al saldo y al acumulado
    db.usuarios.update_one(
        {"correo": puntos.correo},
        {"$inc": {"puntos": puntos.puntos, "puntos_acumulados": puntos.puntos}},
        upsert=False,
    )
    db.historial.insert_one(
        {
            "usuario": puntos.correo,
            "accion": "escaneo",
            "detalle": f"+{puntos.puntos} puntos por reciclaje",
            "fecha": datetime.utcnow(),
        }
    )
    nuevo = get_user(puntos.correo)
    return {
        "mensaje": "Puntos agregados",
        "puntos": int_or_0(nuevo, "puntos"),
        "puntos_acumulados": int_or_0(nuevo, "puntos_acumulados"),
    }


# -------- Listar premios -------------------------------
@app.get("/premios")
def listar_premios():
    # quita _id en la proyección
    return list(db.premios.find({}, {"_id": 0}))


# -------- Canjear premio -------------------------------
@app.post("/puntos/canjear")
def canjear_premio(data: Canje):
    user = get_user(data.correo)
    if not user:
        return {"error": "Usuario no encontrado"}

    premio = db.premios.find_one({"nombre": data.premio})
    if not premio:
        return {"error": "Premio no encontrado"}

    pts_necesarios = int(premio.get("puntos_necesarios", 0))
    stock_actual = int(premio.get("stock", 0))
    saldo_actual = int_or_0(user, "puntos")

    if stock_actual <= 0:
        return {"error": "Premio sin stock"}
    if saldo_actual < pts_necesarios:
        return {"error": "No tienes suficientes puntos"}

    db.usuarios.update_one(
        {"correo": data.correo},
        {"$inc": {"puntos": -pts_necesarios}},  # ¡sólo saldo actual!
    )
    db.premios.update_one({"nombre": data.premio}, {"$inc": {"stock": -1}})
    db.historial.insert_one(
        {
            "usuario": data.correo,
            "accion": "canje",
            "detalle": f"Gastó {pts_necesarios} pts por: {data.premio}",
            "fecha": datetime.utcnow(),
        }
    )
    nuevo = get_user(data.correo)
    return {
        "mensaje": f"Canjeaste {data.premio}",
        "puntos": int_or_0(nuevo, "puntos"),
        "puntos_acumulados": int_or_0(nuevo, "puntos_acumulados"),
    }


# -------- Historial ------------------------------------
@app.get("/historial/{correo}")
def ver_historial(correo: str):
    historial = list(db.historial.find({"usuario": correo}, {"_id": 0}))
    historial.sort(key=lambda x: x.get("fecha", datetime.min), reverse=True)
    return historial


# -------- Garbage Classification -----------------------
@app.post("/classify")
async def classify(file: UploadFile = File(...)):
    try:
        # Read the image from the upload
        image_stream = await file.read()

        # Classify the image from the stream
        result = classify_image_from_stream(io.BytesIO(image_stream))

        # Aquí puedes agregar lógica para dar puntos, etc.
        # Por ahora, solo devolvemos el resultado de la clasificación.

        return result
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
