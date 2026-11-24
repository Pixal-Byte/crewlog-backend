FROM python:3.14
WORKDIR /

COPY crewlog ./crewlog
COPY requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

CMD [ "uvicorn", "crewlog.main:create_app", "--factory", "--port", "8200" ]