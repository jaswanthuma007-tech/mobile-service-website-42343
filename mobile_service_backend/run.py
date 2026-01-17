from app import app

if __name__ == "__main__":
    # Bind explicitly to the required container port.
    app.run(host="0.0.0.0", port=3001)
