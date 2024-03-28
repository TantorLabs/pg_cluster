# pg_cluster, кластер высокой доступности на базе решения Patroni

## Структура проекта

```
|-- pg-cluster.yaml			# Main playbook
|-- pki-dir				# Certificates generated using ssl-gen.sh
|   |-- .gitkeep
|-- README.md
|-- inventory
|   |-- group_vars
|   |   |-- etcd.yml
|   |   |-- haproxy.yml
|   |   |-- keepalived.yml
|   |   |-- patroni.yml
|   |   |-- pgbouncer.yml
|   |   |-- prepare_nodes.yml
|   |-- my_inventory
|-- roles
|   |-- etcd					# Role that installs etcd-tantor-all package
|   |   |-- handlers
|   |   |   `-- main.yml
|   |   |-- tasks
|   |   |   |-- main.yml
|   |   |   |-- pki.yml
|   |   |   `-- systemd.yml
|   |   |-- templates
|   |   |   |-- etcd.conf.j2
|   |   |   `-- etcd-tantor.service.j2
|   |-- haproxy					# Role that installs haproxy-tantor-all package
|   |   |-- handlers
|   |   |   `-- main.yml
|   |   |-- tasks
|   |   |   `-- main.yml
|   |   `-- templates
|   |       `-- haproxy.cfg.j2
|   |--keepalived                       # Role that installs keepalived-tantor-all package
|   |   |-- check_scripts
|   |   |   `-- chk_patroni_leader.sh
|   |   |-- handlers
|   |   |   `-- main.yml 					# 
|   |   |-- tasks
|   |   |   `-- main.yml
|   |   `-- templates
|   |       `-- keepalived.conf.j2
|   |-- patroni					# Role that installs patroni-tantor-all package
|   |   |-- handlers
|   |   |   `-- main.yml
|   |   |-- tasks
|   |   |   `-- main.yml
|   |   `-- templates
|   |       |-- patroni.service.j2
|   |       |-- patroni-watchdog.service.j2
|   |       `-- patroni.yml.j2
|   |-- pgbouncer				# Role that installs pgbouncer-tantor-all package
|   |   |-- handlers
|   |   |   `-- main.yml 
|   |   |-- sql
|   |   |   `-- pgbouncer_prepare.sql	# CREATE SCHEMA pgbouncer and FUNCTION pgbouncer.get_auth
|   |   |-- tasks
|   |   |   `-- main.yml
|   |   `-- templates
|   |       |-- pgbouncer.ini.j2
|   |       `-- pgbouncer.service.j2
|   |-- postgres_classic			# Role that installs postgresql package
|   |   `-- tasks
|   |       `-- main.yml
|   |-- postgres_tantordb			# Role that installs tantor-server package
|   |   `-- tasks
|   |       `-- main.yml
|   `-- prepare_nodes			# Role for installing basic utils
|       `-- handlers
|           `-- main.yml
|       `-- tasks
|           `-- main.yml
|-- tools
|   |-- etcd
|   |-- etcd.conf
|   |-- pg_configurator.py
|   `-- ssl-gen.sh
```

![Архитектура](pg_cluster.png)

# Общие сведения

В этом разделе описан порядок развёртывания ``pg_cluster`` с помощью средств автоматизации на базе ``ansible``.
Далее по тексту будут представлены примеры вводимых в терминале команд, нужных для подготовки SSH сессии, проверки корректности настроек ansible и запуска playbook. В качестве примера пользователя в них будет использоваться учётная запись ``admin_user``. При запуске команд в контуре Заказчика данный пользователь должен быть изменён на учётную запись, имеющую беспарольный доступ по SSH ко всем серверам (виртуальным машинам) указанным в файле ``my_inventory``, а также доступ в привилегированный режим (root). В результате работы плейбука на серверах, указанных в файле ``my_inventory`` будет развёрнут кластер выбранной СУБД (tantordb или postgresql), управляемый через patroni.

## Подготовка узлов на базе ОС Astra Linux 1.7

1. Создайте пользователя ``admin_user`` (выполняется на каждом узле из файла ``inventory``):

```bash
adduser admin_user
```

2. Установите git (выполняется на узле, с которого будет запускаться ansible-playbook):

```bash
apt install git
```

3. Скачайте проект (выполняется на узле, с которого будет запускаться ansible-playbook):

```bash
git clone -b tantor-classic https://github.com/TantorLabs/pg_cluster

cd pg_cluster
```

4. Сгенерируйте SSH ключи и загрузите на узлы кластера (выполняется на узле, с которого будет запускаться ansible-playbook):

```bash
ssh-keygen -t rsa -b 4096 -C "admin_user" -f /home/admin_user/pg_lab_ansible -q -N ""

cat /home/admin_user/pg_lab_ansible.pub >> /home/admin_user/.ssh/authorized_keys

ssh-copy-id -i /home/admin_user/pg_lab_ansible.pub admin_user@ip_узла  ( повторите команду для каждого узла из файла inventory)
```

5. Пропишите параметры подключения каждого сервера из ``inventory файла`` для пользователя ``admin_user`` (выполняется на узле, с которого будет запускаться ansible-playbook):

```bash
cat >> $HOME/.ssh/config << EOL  
Host xxx.xxx.xxx.xxx  
     Port 22  
     User admin_user  
     PreferredAuthentications publickey  
     StrictHostKeyChecking no  
     IdentityFile /home/admin_user/pg_lab_ansible  
EOL
```

6. Предоставьте возможность пользователю ``admin_user`` переходить в привилегированный режим (root) без ввода пароля (выполняется на каждом узле из файла inventory).

7. Протестируйте подключение по ``ssh`` пользователя ``admin_user`` (при подключении не должен запрашиваться пароль):

```bash
ssh admin_user@ip_узла
```

## Подготовка Ansible

Подготовка к запуску выполняется на узле, с которого будет запускаться ansible-playbook, и включает в себя следующие шаги:

1. Установите ansible

```bash
apt install python3-pip
python3 -m pip install ansible=="xxx" # укажите максимально доступную версию
```

2. В файле ``inventory/group_vars/prepare_nodes.yml`` измените значение переменных ``USERNAME:PASSWORD`` на имя пользователя и пароль для доступа к репозиторию Tantor DB.

3. В файле ``inventory/group_vars/keepalived.yml`` измените значение переменной ``cluster_vip_1`` на IP, который будет использоваться keepalived для выделенного виртуального адреса.

4. Заполните ``inventory`` файл ``inventory/my_inventory``

После заполнения файла ``my_inventory`` рекомендуется убедиться, что все серверы доступны для подключения к ним по SSH с указанием требуемого пользователя. Для этого выполните следующую команду в терминале:

```bash
ansible all -i inventory/my_inventory -m ping -u admin_user
```

Результатом выполнения команды выше будет ответ от каждого из доступных серверов (виртуальных машин) в следующем формате:

```bash
<device_fqdn_name> | SUCCESS => {
    "ansible_facts": {
        "discovered_interpreter_python": "/usr/bin/<host_python_version>"
    },
    "changed": false,
    "ping": "pong"
}
```

Данный вывод для каждого сервера, описанного в файле ``my_inventory``, означает успешное подключение к нему по SSH. Если в результате ответа от какого-либо сервера (виртуальной машины) сообщение отличалось от шаблона выше - проверьте возможность подключения к нему через ключ от имени пользователя, передаваемого при помощи флага ``-u``. При необходимости подключаться только с вводом пароля (без использования ключей) - необходимо добавлять флаги ``-kK`` к запуску команд и вводить пароль для SSH-подключения (флаг ``-k``) и для перехода пользователя в привилегированный режим (root) (флаг ``-K``):

## Особенности запуска

Плейбук допускает возможность разделения каталогов pg_data, pg_wal и pg_log.
В случае необходимости размещения WAL-журналов в отдельной папки необходимо внести изменения в файл ``inventory/groupvars/patroni.yml``:

* убрать комментарий для переменной ``patroni_pg_wal_dir`` и в ней прописать каталог для размещения WAL-журналов;
* для переменной ``patroni_bootstrap_initdb`` добавить параметр ``waldir`` и проверить, что он ссылается на переменную ``patroni_pg_wal_dir``;
* для выбранного метода создания реплик (по-умолчанию ``patroni_pg_basebackup``) добавить параметр ``waldir`` со значением ``bulk_wal_dir``;

В случае необходимости размещения LOG-журналов:

* убрать комментарий для переменной ``patroni_pg_log_dir`` и в ней прописать каталог для размещения LOG-журналов;

## Запуск плейбука

Одна из задач из плейбука выполняется на том же узле, с которого запускается ansible (контрольный сервер). В случае, если пользователь, под которым ведётся запуск, не имеет на этом сервере возможность беспарольного доступа в привелигированный режим (root) - необходимо добавить флаг ``-K`` к команде запуска и ввести пароль.

Существует несколько вариантов запуска Ansible: с возможностью установки TantorDB либо классического PostgreSQL в качестве СУБД.

Для установки СУБД TantorDB используйте следующую команду:

```bash
ansible-playbook -i inventory/my_inventory -u admin_user -e "postgresql_vendor=tantordb major_version=15" pg-cluster.yaml -K
```

Для установки СУБД TantorDB используйте следующую команду:

```bash
ansible-playbook -i inventory/my_inventory -u admin_user -e "postgresql_vendor=classic major_version=11" pg-cluster.yaml -K
```

В командах выше замените значение параметра ``major_version`` на версию СУБД, которую необходимо установить, а параметр ``admin_user`` на пользователя, имеющего беспарольный доступ к серверам из файла ``my_inventory`` с возможностью перехода в привилегированный режим (root).
