FROM python:3.11.16-slim-bookworm
ARG VERSION=0.1.2-beta.1
ARG AUTHORS=[]
ARG COMPANY={}
ARG README_URL=""
ARG LINKS={}
ARG SOURCE_URL=""
ENV ATLAS_VERSION=${VERSION}
ENV ATLAS_SOURCE_URL=${SOURCE_URL}
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY atlas ./atlas
EXPOSE 8097/tcp
LABEL version="${VERSION}"
LABEL authors="${AUTHORS}"
LABEL company="${COMPANY}"
LABEL readme="${README_URL}"
LABEL links="${LINKS}"
LABEL tags='["water-quality","data-collection","sensors"]'
LABEL org.opencontainers.image.title="Atlas Sensors"
LABEL org.opencontainers.image.version="${VERSION}"
LABEL org.opencontainers.image.source="${SOURCE_URL}"
LABEL type="device-integration"
LABEL requirements="core >= 1.1"
LABEL permissions='{"ExposedPorts":{"8097/tcp":{}},"HostConfig":{"Binds":["/usr/blueos/extensions/atlas-sensors:/data","/dev:/dev"],"DeviceCgroupRules":["c 89:* rwm", "c 188:* rwm"],"PortBindings":{"8097/tcp":[{"HostPort":""}]}}}'
CMD ["python", "-m", "atlas", "--data-dir", "/data"]
