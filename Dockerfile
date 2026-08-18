FROM ghcr.io/tn-aixpa/rs-landslide-monitoring:0.15
RUN conda init bash && . ~/.bashrc 

WORKDIR /app
COPY src/inference/job_insar_preprocessing.py .
COPY src/inference/job_feature_extraction.py .
COPY src/core/ /app/utils

ENTRYPOINT [ "/bin/bash" ]