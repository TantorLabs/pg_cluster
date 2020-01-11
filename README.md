# pg_cluster

PostgreSQL HA cluster on Patroni

### Requirements

- Ansible 2.9
- Ubuntu 18.04 (bionic)

### Installation

Prepare deployment node:

    sudo apt-get update
    sudo apt-get upgrade -y
    sudo apt-get install -y golang-cfssl
    sudo apt-get install python tree -y
    sudo apt install software-properties-common
    sudo apt-add-repository --yes --update ppa:ansible/ansible
    sudo apt install ansible
    ansible --version
    >> ansible 2.9.2

Create ssh-key for ansible:

    ssh-keygen
    # push public key on nodes: NODE_1, NODE_2, NODE_3 (cluster nodes)
    cat > ~/.ssh/authorized_keys << EOL
    ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDIDYbEAunHBDCL39ZoSt+F73jb9ufh/b0ml+FRFmsT8WzyNY2IJfvVb8kTCV+n9RI0m8eBrIZY90yDNFHvTVQAgnvAPnsSrEuBCrLFz1RuvIZ9uOuFXN+l4f9yjqIVaNldKl+rXe/6IXYD790bRyiwuv9QvpkAjKJhR+r+8+no/vcfdVZlq8ppq7lCj+UKlCFGG/VA67ghgOgTMT2cjekJFMkNUfXbXn7YExgRf0An4NZNusV/9EW7PkTISLwgPcI1Bof3CFhfTXbR6NmUfloNO2lr+bUXmBEJWKm4sE67N4gqBKtN8PaOi/9wX3oCQdFQmL3Egq/86l1P7l74Tw0d root@ansible_node
    EOL

Configure python on cluster nodes:

    ln -s /usr/bin/python3 /usr/bin/python


Configure inventory file:

    cat > /etc/ansible/hosts << EOL
    inv_cluster:
      hosts:
        NODE_1:
          ansible_ssh_host: 185.246.65.116
        NODE_2:
          ansible_ssh_host: 185.246.65.118
        NODE_3:
          ansible_ssh_host: 185.246.65.119
    inv_pg:
      hosts:
        NODE_1:
          ansible_ssh_host: 185.246.65.116
        NODE_2:
          ansible_ssh_host: 185.246.65.118
    inv_etcd:
      hosts:
        NODE_1:
          ansible_ssh_host: 185.246.65.116
        NODE_2:
          ansible_ssh_host: 185.246.65.118
        NODE_3:
          ansible_ssh_host: 185.246.65.119
    EOL

Test ansible connection:

    # on NODE_DEV
    export ANSIBLE_HOST_KEY_CHECKING=False		# to avoid  WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!
    # or clear the contents of known_hosts
    > ~/.ssh/known_hosts
    # test connection
    ansible -m ping inv_cluster

Generate etcd keys:

    cd tools
    # format of etcd.conf: <external-DNS>,<external-IP>,<AWS-internal-DNS>,<AWS-internal-IP>
    cat > etcd.conf << EOL
    NODE_1,185.246.65.116,NODE_1,185.246.65.116
    NODE_2,185.246.65.118,NODE_2,185.246.65.118
    NODE_3,185.246.65.119,NODE_3,185.246.65.119
    EOL
    ./ssl-gen.sh etcd.conf
	cd ..

Deploy cluster:

    ansible-playbook pg-cluster.yaml

Deploy specific role:

    ansible-playbook pg-cluster.yaml --tags "postgres"
	# prepare_nodes, etcd, pgbouncer, haproxy

Check etcd status:

    # on NODE_1
    etcdctl --endpoints https://185.246.65.116:2379 \
    --ca-file=/var/lib/etcd/pg-cluster.pki/ca.pem \
    --cert-file=/var/lib/etcd/pg-cluster.pki/NODE_1.pem \
    --key-file=/var/lib/etcd/pg-cluster.pki/NODE_1-key.pem \
    --debug cluster-health

    # or
    ... --debug member list

    ... --version
    >> etcdctl version: 3.3.18
    API version: 2

    ... ls --recursive --sort -p /service

### How to

Manual start patroni:

    ps -ef | grep "bin/patroni" | grep -v grep | awk '{print $2}' | xargs kill
    su -l postgres -c "/usr/bin/python3 /usr/local/bin/patroni /etc/patroni/NODE_1.yml"

### Links

https://koudingspawn.de/setup-an-etcd-cluster/  
https://lzone.de/cheat-sheet/etcd  
https://coreos.com/os/docs/latest/generate-self-signed-certificates.html  
https://sadique.io/blog/2016/11/11/setting-up-a-secure-etcd-cluster-behind-a-proxy/  
https://github.com/portworx/cfssl-certs  
https://github.com/andrewrothstein/ansible-etcd-cluster  
https://github.com/kostiantyn-nemchenko/ansible-role-patroni  
