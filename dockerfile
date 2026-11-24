FROM python:3.14
WORKDIR /

COPY crewlog ./crewlog
COPY requirements.txt ./requirements.txt
#RUN useradd crewlog
#USER crewlog

#RUN python -m venv venv
#RUN source venv/bin/activate
RUN pip install -r requirements.txt

CMD [ "uvicorn", "crewlog.main:create_app", "--factory", "--port", "8200" ]