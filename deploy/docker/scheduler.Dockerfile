FROM python:3.12

WORKDIR /usr/src/app

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY MANIFEST.in setup.py .
RUN pip install .

CMD ["python3", "-m", "mtracker.scheduler"]
