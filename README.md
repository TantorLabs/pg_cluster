# pg_cluster

PostgreSQL HA cluster on Patroni

### Requirements

- ansible 2.9
- Ubuntu 18.04 (bionic)

### Installation

Prepare deployment node:

    sudo apt-get update
    sudo apt-get upgrade -y
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
    cluster:
      hosts:
        NODE_1:
          ansible_ssh_host: 185.246.65.116
        NODE_2:
          ansible_ssh_host: 185.246.65.118
        NODE_3:
          ansible_ssh_host: 185.246.65.119
    pg:
      hosts:
        NODE_1_PG:
          ansible_ssh_host: 185.246.65.116
        NODE_2_PG:
          ansible_ssh_host: 185.246.65.118
    etcd:
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
    											# or clear the contents of ~/.ssh/known_hosts
    ansible -m ping cluster

Generate etcd keys:

    cd pki-dir
    openssl req -newkey rsa:2048 -new -nodes -x509 -days 3650 -keyout NODE_1-key.pem -out NODE_1.pem
    openssl req -newkey rsa:2048 -new -nodes -x509 -days 3650 -keyout NODE_2-key.pem -out NODE_2.pem
    openssl req -newkey rsa:2048 -new -nodes -x509 -days 3650 -keyout NODE_3-key.pem -out NODE_3.pem
    openssl req -newkey rsa:2048 -new -nodes -x509 -days 3650 -keyout ca-key.pem -out ca.pem

Deploy cluster:

    ansible-playbook pg-cluster.yaml

