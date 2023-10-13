# Установка на RedOS 7.3

**На каждом из узлов кластера создать пользователя pg-lab:**

adduser pg-lab

**Установить git:**

yum install git

**Скачать проект:**

git clone -b redos-tantor <https://github.com/TantorLabs/pg_cluster>

cd pg_cluster

**Сгенерировать SSH ключи и загрузить на узлы кластера:**

ssh-keygen -t rsa -b 4096 -C "pg-lab" -f /home/pg-lab/pg_lab_ansible -q -N ""

ssh-copy-id -i /home/pg-lab/pg_lab_ansible.pub pg-lab@ip_узла  (повторить для каждого узла)

**Прописать параметры подключения для пользователя pg-lab:**

cat $HOME/.ssh/config

Host 192.168.56.*
     Port 22
     User pg-lab
     PreferredAuthentications publickey
     StrictHostKeyChecking no
     IdentityFile /home/pg-lab/pg_lab_ansible

**Прописать на каждом узле кластера возможность выполнения sudo для пользователя pg-lab без ввода пароля.**

**Протестировать подключение по ssh пользователя pg-lab (при подклбчении не должен запрашиваться пароль):**

ssh pg-lab@ip_узла

**В файле roles/postgres/tasks/main.yml в строке "baseurl: https://USERNAME:PASSWORD@nexus.tantorlabs.ru/repository/centos-7" заменить USERNAME:PASSWORD на имя пользователя и пароль для доступа к репозиторию Tantor DB.**

**В файле defaults/main.yml в строке cluster_vip: "10.128.0.199" заменить ip на ip, который будет использоваться keepalived для выделенного виртуального адреса.**

**В файле my_inventory заменить ip-адреса узлов кластера на актуальные.**

**Установить Ansible:**

yum install bionic ansible

**Запустить плейбук:**

ansible-playbook pg-cluster.yaml -i my_inventory
