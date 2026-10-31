# Annuaire de TEST (OpenLDAP, paquet Debian maintenu) simulant l'Active Directory de la Ville (D-007).
# LDAPS sur 1636, overlay memberOf, comptes fictifs. Jamais en production.
FROM debian:trixie-slim@sha256:f6b08b09a05725f9431502d3b5714f5c4576e82c1a84fa1debe0c24a7e0c3ec4
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends slapd ldap-utils ca-certificates \
    && rm -rf /var/lib/apt/lists/* /etc/ldap/slapd.d /var/lib/ldap/* \
    && mkdir -p /var/lib/ldap /run/slapd /etc/ldap/donnees \
    && chown -R openldap:openldap /var/lib/ldap /run/slapd
COPY deploy/dev/annuaire/demarrer.sh /usr/local/bin/demarrer.sh
COPY deploy/dev/annuaire/annuaire.ldif.modele /etc/ldap/donnees/annuaire.ldif.modele
RUN chmod 0755 /usr/local/bin/demarrer.sh
USER openldap
EXPOSE 1389 1636
HEALTHCHECK --interval=10s --timeout=5s --retries=20 CMD ["sh", "-c", "kill -0 $(cat /run/slapd/slapd.pid)"]
CMD ["/usr/local/bin/demarrer.sh"]
