FROM python:3.10

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir --no-input -r ./requirements.txt

ENV FLASK_DEBUG=True

CMD ["python", "src/calexa.py"]

EXPOSE 5000