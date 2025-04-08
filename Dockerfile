FROM python:3.11-bullseye

WORKDIR /TG-BOT

RUN pip install --no-cache-dir --upgrade pip 

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV PORT=8000
EXPOSE 8000

CMD ["python", "bot.py"]