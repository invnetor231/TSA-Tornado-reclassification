import os
import base64
import binascii
import requests
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGES = 5
MAX_IMAGE_BYTES = 5 * 1024 * 1024
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


@app.get("/")
def home():
    return send_from_directory("static", "index.html")


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "TSA International",
        "gemini_configured": bool(os.environ.get("GEMINI_API_KEY"))
    })


@app.post("/api/analyze")
def analyze():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return jsonify({
            "error": "GEMINI_API_KEY não configurada. Adicione a variável em Render > Environment."
        }), 503

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Corpo JSON inválido."}), 400

    prompt = payload.get("prompt", "")
    images = payload.get("images", [])

    if not isinstance(prompt, str) or not prompt.strip():
        return jsonify({"error": "Prompt técnico ausente."}), 400
    if not isinstance(images, list) or not images:
        return jsonify({"error": "Envie pelo menos uma fotografia."}), 400
    if len(images) > MAX_IMAGES:
        return jsonify({"error": "O limite é de 5 fotografias por análise."}), 400

    parts = [{"text": prompt.strip()}]

    for index, image in enumerate(images, start=1):
        if not isinstance(image, dict):
            return jsonify({"error": f"Formato inválido na fotografia {index}."}), 400

        mime_type = image.get("mimeType")
        encoded = image.get("data")

        if mime_type not in ALLOWED_MIME_TYPES:
            return jsonify({"error": f"Formato não permitido na fotografia {index}. Use JPEG, PNG ou WEBP."}), 400
        if not isinstance(encoded, str) or not encoded:
            return jsonify({"error": f"Dados ausentes na fotografia {index}."}), 400

        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return jsonify({"error": f"Base64 inválido na fotografia {index}."}), 400

        if len(raw) > MAX_IMAGE_BYTES:
            return jsonify({"error": f"A fotografia {index} excede 5 MB."}), 413

        # Confere a assinatura binária para reduzir falsificação de MIME type.
        signatures = {
            "image/jpeg": raw.startswith(b"\\xff\\xd8\\xff"),
            "image/png": raw.startswith(b"\\x89PNG\\r\\n\\x1a\\n"),
            "image/webp": len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP",
        }
        if not signatures.get(mime_type, False):
            return jsonify({"error": f"O conteúdo da fotografia {index} não corresponde ao formato declarado."}), 400

        parts.append({
            "inline_data": {
                "mime_type": mime_type,
                "data": encoded
            }
        })

    model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip()
    url = f"{GEMINI_API_BASE}/{model}:generateContent"

    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
            "maxOutputTokens": 5000
        }
    }

    try:
        response = requests.post(
            url,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key
            },
            json=body,
            timeout=(15, 120)
        )
    except requests.Timeout:
        return jsonify({"error": "Tempo limite da conexão com Gemini excedido. Tente novamente."}), 504
    except requests.RequestException:
        app.logger.exception("Falha de conexão com Gemini")
        return jsonify({"error": "Não foi possível conectar ao serviço Gemini."}), 502

    try:
        result = response.json()
    except ValueError:
        result = {}

    if not response.ok:
        # Não devolve cabeçalhos, chave ou conteúdo sensível ao navegador.
        message = result.get("error", {}).get("message", "Erro retornado pelo Gemini.")
        app.logger.warning("Gemini HTTP %s: %s", response.status_code, message[:500])
        safe_message = message[:350]
        return jsonify({"error": f"Gemini HTTP {response.status_code}: {safe_message}"}), 502

    candidates = result.get("candidates") or []
    response_parts = (
        candidates[0].get("content", {}).get("parts", [])
        if candidates else []
    )
    text = "\\n".join(
        part.get("text", "")
        for part in response_parts
        if isinstance(part, dict) and part.get("text")
    ).strip()

    if not text:
        return jsonify({"error": "Gemini não retornou conteúdo analisável. Verifique bloqueios ou limites da API."}), 502

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```json", "", 1).replace("```", "").strip()

    try:
        analysis = __import__("json").loads(cleaned)
    except (ValueError, TypeError):
        return jsonify({"error": "Gemini retornou uma resposta que não está em JSON válido."}), 502

    return jsonify({"analysis": analysis})


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "A solicitação excedeu o limite total de 30 MB."}), 413


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
