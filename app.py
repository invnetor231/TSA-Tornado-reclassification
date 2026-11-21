import os
import re
import json
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


def get_gemini_api_key():
    """
    Obtém a chave sem expor seu valor.
    Prioridade: GEMINI_API_KEY do ambiente, GOOGLE_API_KEY como alternativa,
    e por último um arquivo .env local (útil em testes locais).
    """
    # Primeiro, procura os nomes exatos e também tolera espaços no nome.
    normalized = {
        str(name).strip().upper(): str(value).strip()
        for name, value in os.environ.items()
        if value is not None and str(value).strip()
    }

    key = normalized.get("GEMINI_API_KEY") or normalized.get("GOOGLE_API_KEY")
    if key:
        source = (
            "GEMINI_API_KEY" if normalized.get("GEMINI_API_KEY")
            else "GOOGLE_API_KEY"
        )
        return key, source

    # Leitura simples de .env sem exigir dependência adicional.
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.isfile(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as env_file:
                for line in env_file:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    name, value = line.split("=", 1)
                    if name.strip().upper() in {"GEMINI_API_KEY", "GOOGLE_API_KEY"}:
                        value = value.strip().strip('"').strip("'")
                        if value:
                            return value, ".env"
        except OSError:
            app.logger.exception("Não foi possível ler o arquivo .env")

    return "", None


@app.get("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/health")
def health():
    api_key, key_source = get_gemini_api_key()
    # Nunca retorna a chave nem qualquer parte dela.
    return jsonify({
        "status": "ok",
        "service": "TSA International",
        "gemini_configured": bool(api_key),
        "gemini_key_source": key_source,
        "checked_environment_names": ["GEMINI_API_KEY", "GOOGLE_API_KEY"]
    })


@app.post("/api/analyze")
def analyze():
    api_key, _key_source = get_gemini_api_key()
    if not api_key:
        return jsonify({
            "error": "GEMINI_API_KEY não configurada. Adicione essa variável em Render > Environment."
        }), 503

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Corpo JSON inválido. Envie Content-Type: application/json."}), 400

    prompt = payload.get("prompt", "")
    images = payload.get("images", [])

    if not isinstance(prompt, str) or not prompt.strip():
        return jsonify({"error": "Prompt técnico ausente."}), 400
    if len(prompt) > 30000:
        return jsonify({"error": "O texto da análise excede o limite permitido."}), 413
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
            return jsonify({
                "error": f"Formato não permitido na fotografia {index}. Use JPEG, PNG ou WEBP."
            }), 400

        if not isinstance(encoded, str) or not encoded.strip():
            return jsonify({"error": f"Dados ausentes na fotografia {index}."}), 400

        # Aceita tanto Base64 puro quanto uma Data URL do FileReader.
        encoded = encoded.strip()
        if encoded.startswith("data:"):
            header, separator, encoded_data = encoded.partition(",")
            if not separator or ";base64" not in header.lower():
                return jsonify({"error": f"Data URL inválida na fotografia {index}."}), 400
            if header[5:].split(";", 1)[0].lower() != mime_type:
                return jsonify({"error": f"O MIME type da fotografia {index} não corresponde ao conteúdo enviado."}), 400
            encoded = encoded_data

        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return jsonify({"error": f"Base64 inválido na fotografia {index}."}), 400

        if not raw:
            return jsonify({"error": f"A fotografia {index} está vazia."}), 400
        if len(raw) > MAX_IMAGE_BYTES:
            return jsonify({"error": f"A fotografia {index} excede 5 MB."}), 413

        # Assinaturas binárias corretas dos formatos aceitos.
        signatures = {
            "image/jpeg": raw.startswith(b"\xff\xd8\xff"),
            "image/png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/webp": len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP",
        }
        if not signatures.get(mime_type, False):
            return jsonify({
                "error": f"O conteúdo da fotografia {index} não corresponde ao formato declarado."
            }), 400

        parts.append({
            "inline_data": {
                "mime_type": mime_type,
                "data": base64.b64encode(raw).decode("ascii")
            }
        })

    model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip()
    if not model or not re.fullmatch(r"[A-Za-z0-9._-]+", model):
        return jsonify({"error": "A variável GEMINI_MODEL está inválida."}), 500

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
        return jsonify({
            "error": "Tempo limite da conexão com Gemini excedido. Tente novamente."
        }), 504
    except requests.RequestException:
        app.logger.exception("Falha de conexão com Gemini")
        return jsonify({"error": "Não foi possível conectar ao serviço Gemini."}), 502

    try:
        result = response.json()
    except ValueError:
        result = {}

    if not response.ok:
        error_data = result.get("error", {}) if isinstance(result, dict) else {}
        message = error_data.get("message", "Erro retornado pelo Gemini.")
        app.logger.warning("Gemini HTTP %s: %s", response.status_code, str(message)[:500])
        return jsonify({
            "error": f"Gemini HTTP {response.status_code}: {str(message)[:350]}"
        }), 502

    candidates = result.get("candidates", []) if isinstance(result, dict) else []
    if not candidates:
        feedback = result.get("promptFeedback", {}) if isinstance(result, dict) else {}
        block_reason = feedback.get("blockReason")
        if block_reason:
            return jsonify({
                "error": f"Gemini bloqueou a solicitação ({block_reason}). Revise a fotografia ou o prompt."
            }), 422
        return jsonify({
            "error": "Gemini não retornou candidatos. Verifique os limites e a disponibilidade do modelo."
        }), 502

    candidate = candidates[0] if isinstance(candidates[0], dict) else {}
    content = candidate.get("content", {}) or {}
    response_parts = content.get("parts", []) if isinstance(content, dict) else []

    # Junta corretamente os blocos de texto retornados pelo Gemini.
    response_text = "\n".join(
        part.get("text", "")
        for part in response_parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ).strip()

    if not response_text:
        finish_reason = candidate.get("finishReason", "desconhecido")
        return jsonify({
            "error": f"Gemini não retornou conteúdo analisável. Motivo: {finish_reason}."
        }), 502

    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, count=1, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned, count=1)

    try:
        analysis = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        app.logger.warning("Gemini retornou conteúdo que não pôde ser convertido em JSON.")
        return jsonify({
            "error": "Gemini retornou uma resposta fora do formato JSON esperado. Tente novamente."
        }), 502

    return jsonify({"analysis": analysis})


@app.errorhandler(413)
def too_large(_error):
    return jsonify({
        "error": "A solicitação excedeu o limite total de 30 MB."
    }), 413


@app.errorhandler(404)
def not_found(_error):
    return jsonify({"error": "Rota não encontrada."}), 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
