#!/bin/sh
# Démarrage de l'annuaire de test : configuration slapd, puis chargement des comptes fictifs
# par ldapadd (et non slapadd) pour que l'overlay memberOf calcule les appartenances.
set -eu

S=/run/secrets
lire() { tr -d '\r\n' < "$1"; }
MDP_ADMIN=$(lire "$S/ldap_admin_mot_de_passe")
MDP_SERVICE=$(lire "$S/ldap_mot_de_passe")
MDP_AGENTS=$(lire "$S/mdp_agents_demo")
HASH_ADMIN=$(slappasswd -s "$MDP_ADMIN")
CONF=/tmp/slapd.conf

cat > "$CONF" <<EOF
include /etc/ldap/schema/core.schema
include /etc/ldap/schema/cosine.schema
include /etc/ldap/schema/inetorgperson.schema
include /etc/ldap/schema/nis.schema
modulepath /usr/lib/ldap
moduleload back_mdb
moduleload memberof
moduleload refint
pidfile /run/slapd/slapd.pid
TLSCertificateFile $S/annuaire.crt
TLSCertificateKeyFile $S/annuaire.key
TLSCACertificateFile $S/ac_interne.crt
TLSProtocolMin 3.3
disallow bind_anon
require authc
database mdb
maxsize 104857600
suffix "dc=chatillon,dc=test"
rootdn "cn=admin,dc=chatillon,dc=test"
rootpw $HASH_ADMIN
directory /var/lib/ldap
index objectClass,uid,member,memberOf eq
overlay memberof
memberof-group-oc groupOfNames
memberof-member-ad member
memberof-memberof-ad memberOf
memberof-refint TRUE
overlay refint
refint_attributes member
access to attrs=userPassword by self write by anonymous auth by * none
access to * by dn.exact="cn=svc-equipements,ou=services,dc=chatillon,dc=test" read by self read by * none
EOF

slapd -f "$CONF" -h "ldap://0.0.0.0:1389/ ldaps://0.0.0.0:1636/" -d 0 &
PID=$!
for _ in $(seq 1 50); do
  ldapsearch -x -H ldap://127.0.0.1:1389 -D "cn=admin,dc=chatillon,dc=test" -w "$MDP_ADMIN" -b "" -s base >/dev/null 2>&1 && break
  sleep 0.2
done

if ! ldapsearch -x -H ldap://127.0.0.1:1389 -D "cn=admin,dc=chatillon,dc=test" -w "$MDP_ADMIN" -b "dc=chatillon,dc=test" -s base >/dev/null 2>&1; then
  sed -e "s|@MDP_SERVICE@|$(slappasswd -s "$MDP_SERVICE")|" -e "s|@MDP_AGENTS@|$(slappasswd -s "$MDP_AGENTS")|" \
    /etc/ldap/donnees/annuaire.ldif.modele > /tmp/annuaire.ldif
  ldapadd -x -H ldap://127.0.0.1:1389 -D "cn=admin,dc=chatillon,dc=test" -w "$MDP_ADMIN" -f /tmp/annuaire.ldif >/dev/null
  rm -f /tmp/annuaire.ldif
  echo "Annuaire de test initialisé."
fi
wait $PID
