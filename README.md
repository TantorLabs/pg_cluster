# pg_cluster, кластер высокой доступности на базе решения Patroni

## Структура проекта

```
|-- defaults
|   `-- main.yml				# Default settings for: patroni, haproxy, pgbouncer
|-- pg-cluster.yaml			# Main playbook
|-- pki-dir				# Certificates generated using ssl-gen.sh
|   |-- ca-key.pem
|   |-- ca.pem
|   |-- ...
|-- README.md
|-- roles
|   |-- etcd					# 
|   |   |-- defaults
|   |   |   `-- main.yml
|   |   |-- handlers
|   |   |   `-- main.yml
|   |   |-- tasks
|   |   |   |-- main.yml
|   |   |   |-- pki.yml
|   |   |   `-- systemd.yml
|   |   |-- templates
|   |   |   |-- etcd.conf.j2
|   |   |   `-- etcd.service.j2
|   |   `-- vars
|   |       `-- main.yml
|   |-- haproxy					# 
|   |   |-- tasks
|   |   |   `-- main.yml
|   |   `-- templates
|   |       `-- haproxy.cfg.j2
|   |--keepalived
|   |   |-- check_scripts
|   |   |   `-- chk_patroni_async.sh
|   |   |   `-- chk_patroni_leader.sh
|   |   |   `-- chk_patroni_sync.sh
|   |   |-- handlers
|   |   |   `-- main.yml 					# 
|   |   |-- tasks
|   |   |   `-- main.yml
|   |   `-- templates
|   |       `-- keepalived.conf.j2
|   |   `-- vars
|   |       `-- main.yml
|   |-- patroni					# 
|   |   |-- handlers
|   |   |   `-- main.yml
|   |   |-- tasks
|   |   |   `-- main.yml
|   |   `-- templates
|   |       |-- patroni.service.j2
|   |       |-- patroni-watchdog.service.j2
|   |       `-- patroni.yml.j2
|   |-- pgbouncer				# 
|   |   |-- sql
|   |   |   `-- pgbouncer_prepare.sql	# CREATE SCHEMA pgbouncer and FUNCTION pgbouncer.get_auth
|   |   |-- tasks
|   |   |   `-- main.yml
|   |   `-- templates
|   |       |-- pgbouncer.ini.j2
|   |       `-- pgbouncer.service.j2
|   |-- postgres				# v12.X
|   |   `-- tasks
|   |       `-- main.yml
|   `-- prepare_nodes			# Role for installing basic utils
|       `-- tasks
|           `-- main.yml
|-- tools
|   |-- etcd
|   |-- etcd.conf
|   `-- ssl-gen.sh
`-- vars
	`-- main.yml		# Repo and modules for patroni and postgres
```

![Архитектура](pg_cluster.png)

# Установка на Astra Linux 1.7

**На каждом из узлов кластера создать пользователя pg-lab:**

```bash
adduser pg-lab
```

**Установить git:**

```bash
apt install git
```

**Скачать проект:**

```bash
git clone -b astra-tantor https://github.com/TantorLabs/pg_cluster

cd pg_cluster
```

**Сгенерировать SSH ключи и загрузить на узлы кластера:**

```bash
ssh-keygen -t rsa -b 4096 -C "pg-lab" -f /home/pg-lab/pg_lab_ansible -q -N ""

cat /home/pg-lab/pg_lab_ansible.pub >> /home/pg-lab/.ssh/authorized_keys

ssh-copy-id -i /home/pg-lab/pg_lab_ansible.pub pg-lab@ip_узла  (повторить для каждого узла)
```

**Прописать параметры подключения для пользователя pg-lab:**

```bash
cat >> $HOME/.ssh/config << EOL  
Host 192.168.56.*  
     Port 22  
     User pg-lab  
     PreferredAuthentications publickey  
     StrictHostKeyChecking no  
     IdentityFile /home/pg-lab/pg_lab_ansible  
EOL
```

**Прописать на каждом узле кластера возможность выполнения sudo для пользователя pg-lab без ввода пароля.**

**Протестировать подключение по ssh пользователя pg-lab (при подклбчении не должен запрашиваться пароль):**

```bash
ssh pg-lab@ip_узла
```

**Сгенерировать ключи для etcd:**

```bash
cd tools

cat etcd.conf


pg-cluster-01,ip_первого_узла,pg-cluster-01,ip_первого_узла  
pg-cluster-02,ip_второго_узла,pg-cluster-02,ip_второго_узла  
pg-cluster-03,ip_третьего_узла,pg-cluster-03,ip_третьего_узла  


./ssl-gen.sh etcd.conf
```

**В файле vars/main.yml в строке pg_apt_repo: "deb [arch=amd64] https://USERNAME:PASSWORD@nexus.tantorlabs.ru/repository/astra-smolensk-1.7 smolensk main" заменить USERNAME:PASSWORD на имя пользователя и пароль для доступа к репозиторию Tantor DB.**

**В файле defaults/main.yml в строке cluster_vip: "10.128.0.199" заменить ip на ip, который будет использоваться keepalived для выделенного виртуального адреса.**

**В файле my_inventory заменить ip-адреса узлов кластера на актуальные.**

**Установить Ansible:**

В файл /etc/apt/sources.list дописать строку deb http://ppa.launchpad.net/ansible/ansible/ubuntu bionic main

```bash
apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 93C4A3FD7BB9C367

apt update

apt install -t bionic ansible
```

**Запустить плейбук:**

```bash
ansible-playbook pg-cluster.yaml -i my_inventory
```




