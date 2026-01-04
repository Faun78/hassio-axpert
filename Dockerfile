ARG BUILD_FROM
FROM $BUILD_FROM

ENV LANG C.UTF-8

COPY requirements.txt /

RUN apk add --no-cache jq build-base python3-dev libffi-dev openssl-dev && \
  pip install -r requirements.txt && \
  apk del build-base python3-dev libffi-dev openssl-dev && \
  rm -rf /root/.cache

COPY monitor.py /
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
