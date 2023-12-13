# Installation
```bash
apt install -y python3-pip
pip3 install -r requirements.txt
```

# Before usage you need to make sure that the you have Docker installed
```bash
systemctl status docker
```
# if you don't have Docker installed
```bash
apt update
apt install apt-transport-https ca-certificates curl software-properties-common
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
apt-cache policy docker-ce
apt install docker-ce
systemctl status docker
sudo chmod 666 /var/run/docker.sock
```

# Before usage you should have postgresql-client at least installed
```bash
sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add -
apt update && apt --yes remove postgresql\*
apt -y install postgresql-client-15
```

# Usage
```bash
git clone https://github.com/TantorLabs/pg_configurator.git
cd pg_configurator

# Show help
python3 pg_configurator.py -h

# Minimal usage
python3 pg_configurator.py \
        --db-cpu=40 \
        --db-ram=128Gi \
        --db-disk-type=SSD \
        --db-duty=mixed \
        --pg-version=9.6

# Customized usage
python3 pg_configurator.py \
        --db-cpu=40 \
        --db-ram=128Gi \
        --db-disk-type=SSD \
        --db-duty=mixed \
        --replication-enabled=True \
        --pg-version=9.6 \
        --min-conns=200 \
        --max-conns=500 \
        --shared-buffers-part=0.3 \
        --client-mem-part=0.6 \
        --maintenance-mem-part=0.1
```