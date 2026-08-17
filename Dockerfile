FROM ghcr.io/tn-aixpa/rs-landslide-monitoring:0.15
RUN conda init bash && . ~/.bashrc 

WORKDIR /app
COPY src/inference/job_insar_preprocessing.py .
COPY src/inference/job_insar_preprocessing.py .
RUN mkdir /app/utils
COPY src/core/ /app/utils
RUN mkdir /app/data

ENTRYPOINT [ "/bin/bash" ]