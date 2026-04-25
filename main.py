from fastapi import FastAPI
from scalar_fastapi import get_scalar_api_reference
from supabase import Client, create_client

# Hardcoded Supabase credentials
SUPABASE_URL = "https://qokprjircewixfxchqje.supabase.co"
SUPABASE_KEY = "sOqHMVaJVPASREQC"
# PostgreSQL Connection String: postgresql://postgres:sOqHMVaJVPASREQC@db.qokprjircewixfxchqje.supabase.co:5432/postgres

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(
    title="Secret Backend API",
    description="A FastAPI backend with Scalar documentation and Supabase integration.",
    version="1.0.0",
    docs_url=None,  # Disable default Swagger UI
    redoc_url=None, # Disable default ReDoc
)

@app.get("/scalar", include_in_schema=False)
async def scalar_html():
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title=app.title,
    )

@app.get("/items")
async def get_items():
    # Example Supabase query
    # Note: This will fail until a valid SUPABASE_URL and KEY are provided
    try:
        response = supabase.table("items").select("*").execute()
        return response.data
    except Exception as e:
        return {"error": str(e)}

@app.get("/")
async def root():
    return {"message": "Hello from secret-backend!"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
