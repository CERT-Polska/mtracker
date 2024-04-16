FROM python:3.8

WORKDIR /usr/src/app

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY MANIFEST.in setup.py .
RUN pip install .

CMD ["python3", "-m", "mtracker.worker", "/usr/src/app/src/modules"]
