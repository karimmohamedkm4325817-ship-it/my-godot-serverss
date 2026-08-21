from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def home():
    return {"status": "السيرفر يعمل!"}

@app.post("/save_score")
def save_score(data: dict):
    return {"message": "تم الحفظ بنجاح!"}
