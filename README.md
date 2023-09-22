# Установка на Astra Linux 1.7

**На каждом из узлов кластера создать пользователя pg-lab:**

adduser pg-lab

**Установить git**

apt install git

**Скачать проект:**

git clone -b astra-tantor <https://github.com/TantorLabs/pg_cluster>

cd pg_cluster

**Сгенерировать SSH ключи и загрузить на узлы кластера:**

ssh-keygen -t rsa -b 4096 -C "pg-lab" -f /home/pg-lab/pg_lab_ansible -q -N ""

cat /home/pg-lab/pg_lab_ansible.pub >> /home/pg-lab/.ssh/authorized_keys

 ssh-copy-id -i /home/pg-lab/pg_lab_ansible.pub pg-lab@ip_узла  (повторить для каждого узла)

**Прописать параметры подключения для пользователя pg-lab:**

cat >> $HOME/.ssh/config << EOL
Host 192.168.56.*
     Port 22
     User pg-lab
     PreferredAuthentications publickey
     StrictHostKeyChecking no
     IdentityFile /home/pg-lab/pg_lab_ansible
EOL

**Прописать на каждом узле кластера возможность выполнения sudo для пользователя pg-lab без ввода пароля.**

**Протестировать подключение по ssh пользователя pg-lab (при подклбчении не должен запрашиваться пароль):**

ssh pg-lab@ip_узла

**В файле vars/main.yml в строке pg_apt_repo: "deb [arch=amd64] <https://USERNAME:PASSWORD@nexus.tantorlabs.ru/repository/astra-smolensk-1.7> smolensk main" заменить USERNAME:PASSWORD на имя пользователя и пароль для доступа к репозиторию Tantor DB.**

**В файле defaults/main.yml в строке cluster_vip: "10.128.0.199" заменить ip на ip, который будет использоваться keepalived для выделенного виртуального адреса.**

**В файле my_inventory заменить ip-адреса узлов кластера на актуальные.**

**Установить Ansible:**

В файл /etc/apt/sources.list дописать строку deb <http://ppa.launchpad.net/ansible/ansible/ubuntu> bionic main

apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 93C4A3FD7BB9C367

apt update

apt install -t bionic ansible

**Запустить плейбук:**

ansible-playbook pg-cluster.yaml -i my_inventory
