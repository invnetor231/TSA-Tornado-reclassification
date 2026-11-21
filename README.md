# TSA▼ International — pacote Render

Aplicação web Flask com interface HTML/CSS/JavaScript e endpoint de análise multimodal Gemini.

## Estrutura

- `app.py`: servidor Flask e integração segura com Gemini.
- `static/index.html`: interface TSA.
- `requirements.txt`: dependências Python.
- `render.yaml`: configuração de implantação no Render.
- `.env.example`: exemplo de variáveis de ambiente, sem chave real.

## Implantação no Render

1. Extraia o ZIP.
2. Envie o conteúdo da pasta para um repositório GitHub.
3. No Render, selecione **New > Web Service** e conecte o repositório.
4. O Render pode detectar o `render.yaml`. Se configurar manualmente:
   - Runtime: Python 3
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 150`
5. Em **Environment**, adicione:
   - `GEMINI_API_KEY`: sua chave nova do Google AI Studio.
   - `GEMINI_MODEL`: `gemini-3.8-flash`.
6. Salve e faça o deploy.

## Verificação

- Página: `/`
- Saúde do servidor: `/health`
- API de análise: `POST /api/analyze`

O endpoint `/api/analyze` recebe JSON com `prompt` e `images`. Cada imagem deve conter `name`, `mimeType` e `data` (Base64), conforme o frontend.

## Segurança

- Não publique uma chave Gemini no HTML, JavaScript ou repositório.
- A chave usada anteriormente no HTML foi exposta. Revogue-a no Google AI Studio e gere uma nova.
- Configure a nova chave somente nas variáveis de ambiente do Render.
- Fotografias são processadas em memória pela aplicação e encaminhadas ao Gemini; este pacote não implementa armazenamento permanente nem banco de dados.

## Limitações operacionais

- A análise por IA é auxiliar e não emite classificação oficial de tornado.
- Confirme DI, DoD, qualidade construtiva, ancoragem, escala e critérios por avaliação técnica.
- No plano gratuito do Render, o serviço pode entrar em suspensão após inatividade e demorar a acordar.
