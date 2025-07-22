FROM ghcr.io/tn-aixpa/rsde-tools:2.7_b1
RUN conda init bash && . ~/.bashrc 

WORKDIR /app
COPY main.py .
COPY requirements.txt .
COPY merge.py .
RUN mkdir /app/utils
COPY utils /app/utils
RUN mkdir /app/data

RUN python -m pip install -r requirements.txt

ENTRYPOINT [ "/bin/bash" ]