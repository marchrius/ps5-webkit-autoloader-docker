# PS5 WebKit Autoloader Docker + DNS

Un container sempre in ascolto con DNS UDP/TCP, HTTP e HTTPS. Blocca PSN,
aggiornamenti e telemetria PlayStation e serve l'installer ufficiale di
[itsPLK/ps5-webkit-autoloader](https://github.com/itsPLK/ps5-webkit-autoloader).
La build scarica la release **v0.6.1**, completa di frontend e payload incorporati:
non basta copiare la directory frontend del repository, che richiede artefatti generati.
Non scarica aggiornamenti all'avvio e può funzionare senza Internet dopo la build.

## Avvio

### Dispositivo con porta 53 già occupata: macvlan

Il container riceve un IP LAN dedicato e non pubblica porte sul dispositivo:
il DNS già presente può continuare a usare la sua porta 53. Richiede un host
Linux/NAS con Docker rootful, Compose v2 con supporto `!reset`, interfaccia
Ethernet e una rete che accetti più indirizzi MAC sulla stessa porta.

```sh
cp .env.macvlan.example .env
# Modifica HOST_IP, MACVLAN_PARENT, MACVLAN_SUBNET e MACVLAN_GATEWAY.
docker compose config
docker compose up -d --build --force-recreate
docker compose logs -f
```

L'esempio usa `HOST_IP=192.168.1.20`, subnet `192.168.1.0/24`, gateway
`192.168.1.1` e interfaccia `eth0`: verifica i valori sul dispositivo di
destinazione con `ip -br addr` e `ip route`. L'interfaccia potrebbe chiamarsi
`eno1`, `bond0`, `ovs_eth0` o altro. L'IP del container deve essere libero,
diverso da quello del NAS, escluso dal pool DHCP e appartenere alla subnet.
Se il NAS è `192.168.1.10`, assegna al container un altro IP libero.

`COMPOSE_FILE` nel file di esempio carica automaticamente `compose.yaml` e
`compose.macvlan.yaml`. Se usi un gestore NAS che ignora questa variabile,
configura entrambi i file nel progetto oppure esegui esplicitamente:

```sh
docker compose -f compose.yaml -f compose.macvlan.yaml up -d --build --force-recreate
```

Nella configurazione risultante non deve esserci una sezione `ports` per il
servizio. Non basta aggiungere una rete macvlan al file base: l'override
rimuove anche le porte pubblicate. `BIND_IP` non viene usato in questa modalità.
La PS5 deve usare come DNS e destinazione web **l'IP del container** (`HOST_IP`).

Per impostazione del kernel, host e container macvlan non comunicano
direttamente: prova DNS/web dalla PS5 o da un altro computer LAN, oppure usa
`docker compose exec ps5-host python /app/healthcheck.py` sul NAS.
Se usi come upstream DNS il servizio sullo stesso NAS, dovrai predisporre
anche un'interfaccia macvlan sul NAS o un percorso di rete aggiuntivo;
gli upstream pubblici dell'esempio evitano questa dipendenza. L'healthcheck
interno continua a funzionare tramite loopback.
Macvlan non è supportato da Docker Desktop per Mac/Windows; questo progetto
va avviato sul dispositivo Linux di destinazione. Vedi la
[documentazione Docker macvlan](https://docs.docker.com/engine/network/drivers/macvlan/).

### Alternativa con porte pubblicate

Richiede Docker con Compose v2 e un IPv4 LAN stabile per il server.
Usa questa variante quando le porte del dispositivo sono disponibili.

```sh
cp .env.example .env
# Modifica HOST_IP in .env: IPv4 LAN del computer/NAS, ad esempio 192.168.1.10.
docker compose up -d --build
docker compose logs -f
```

### Configurazione della console

Imposta sulla PS5 il DNS primario a `HOST_IP`. Per il secondario usa lo stesso IP
se consentito, oppure un secondo server con le stesse regole. Non usare un DNS
pubblico come secondario: potrebbe aggirare il blocco. Mantieni il gateway del router.
Disabilita gli aggiornamenti automatici nelle impostazioni della console.

Apri **Impostazioni → Guida per l'utente** (il percorso esatto varia con il firmware).
La pagina `https://manuals.playstation.net/document/it/ps5/index.html` viene servita
dal container. Segui l'installer upstream; dopo l'installazione usa il collegamento
WebKit Autoloader creato sulla console. Il container può restare attivo come filtro DNS.
Il supporto al firmware e l'esito dell'installazione dipendono dalla release upstream.

Nella variante con porte pubblicate, le porte **53 UDP/TCP, 80 TCP e 443 TCP** devono essere libere e raggiungibili
dalla console. Compose le pubblica su `BIND_IP`, per default `0.0.0.0` (tutte
le interfacce IPv4). `HOST_IP` è invece l'indirizzo restituito dal DNS alla PS5.
Su Linux nativo puoi impostare `BIND_IP` all'IP LAN del server per limitare il bind.
Un servizio DNS già in ascolto su tutte le interfacce può occupare la porta 53.
Il client PS5 non permette porte DNS alternative.
Su macOS/Windows l'IP deve appartenere al computer, non alla VM Docker; verifica
anche firewall e inoltro UDP di Docker Desktop/Colima. Su Linux il bridge con
porte pubblicate è sufficiente; non occorre `network_mode: host`.

Se Docker restituisce `cannot assign requested address`, l'indirizzo scelto
per il bind non è disponibile sul sistema che esegue il daemon (per esempio
la VM di Colima). Imposta `BIND_IP=0.0.0.0` e ricrea il container con
`docker compose up -d --force-recreate`. Mantieni `HOST_IP` uguale all'IPv4
che la PS5 può effettivamente raggiungere, non all'IP interno del container.

`restart: unless-stopped` riavvia il container dopo crash o riavvio del daemon.
Docker deve avviarsi automaticamente con il server. Il supervisore termina il
container se DNS/web si fermano o falliscono tre controlli consecutivi; Docker
lo riavvia. Il solo stato Docker `unhealthy` normalmente non provocherebbe un riavvio.

## Domini e pagine gestite

Le liste in `config/` sono modificabili e montate in sola lettura nel container.
Riavvia con `docker compose restart` dopo una modifica.

| Dominio | Comportamento |
| --- | --- |
| `manuals.playstation.net` | Serve il frontend upstream tramite `/document/<lingua>/ps5/`; i percorsi degli altri file dipendono dalla release |
| `www.playstation.com` | Reindirizza le richieste web alla radice della Guida locale |
| `get.net.playstation.net` | Reindirizza le richieste web alla Guida locale; endpoint storico dei test di connessione |
| `ps5-autoloader.test` | Alias locale che reindirizza alla Guida |
| `HOST_IP` (IP del container con macvlan) | Accesso diretto al frontend, utile per prove via HTTP |

Gli ingressi diversi dalla Guida sono aggiuntivi: il test di connessione può
limitarsi a fallire senza aprire un browser su PS5. Il metodo di installazione
documentato da upstream resta la Guida utente. Non vengono simulati un accesso
PSN valido o un test di velocità riuscito. Gli endpoint aggiornamenti, `post` ed
`ena` restano bloccati.

`blocked-domains.txt` contiene i suffissi `playstation.net`, `playstation.com`,
`playstation.org`, `scea.com`, `sonyentertainmentnetwork.com`, `sie-rd.com`.
Il blocco include dominio e sottodomini, quindi anche tutti i server regionali
`fXX01`, `dXX01`, `hXX01.ps5.update.playstation.net`, CDN, Store e autenticazione.
Le eccezioni di `redirect-domains.txt` creano record A locali esatti; per esse
AAAA e altri tipi DNS non vengono inoltrati. Non è una lista di singoli IP CDN.

In `.env`:

| Variabile | Significato |
| --- | --- |
| `HOST_IP` | Obbligatoria: IP dedicato al container in macvlan, IP del server con porte pubblicate |
| `COMPOSE_FILE` | In macvlan: `compose.yaml:compose.macvlan.yaml` su Linux |
| `MACVLAN_PARENT` | Interfaccia LAN del dispositivo Docker, es. `eth0` o `bond0` |
| `MACVLAN_SUBNET` | Subnet LAN in formato CIDR, es. `192.168.1.0/24` |
| `MACVLAN_GATEWAY` | IPv4 del router della LAN |
| `BIND_IP` | Solo con porte pubblicate: indirizzo di bind, default `0.0.0.0` |
| `DNS_MODE=selective` | Blocca i suffissi configurati, inoltra gli altri nomi agli upstream |
| `DNS_MODE=offline` | Blocca tutti i nomi tranne le eccezioni locali; nessun inoltro DNS |
| `UPSTREAM_DNS` | IP dei resolver separati da virgole, default `1.1.1.1,9.9.9.9` |
| `LOG_QUERIES=true` | Registra le richieste DNS nei log Docker |
| `AUTOLOADER_VERSION` | Release stabile scaricata durante la build |
| `AUTOLOADER_SHA256` | Facoltativo: digest atteso del file host `.py` |

Per applicare modifiche a `.env`: `docker compose up -d --build`.
Per aggiungere un ingresso browser, aggiungi il suo dominio esatto a
`redirect-domains.txt`: verrà risolto localmente e rimandato alla Guida canonica.

## HTTPS e limiti del blocco

Il container genera un certificato autofirmato per i domini configurati a ogni
avvio, evitando di riutilizzare la chiave privata pubblica inclusa nella release.
Un browser su PC mostrerà un avviso; l'accettazione sulla console dipende da
firmware e contesto browser, come per l'host upstream. DNS da solo non rende un
certificato attendibile e non supera HSTS/certificate pinning. Preferisci la
Guida utente; non è garantita l'intercettazione trasparente di qualsiasi pagina HTTPS.

PSN, Store e servizi correlati smetteranno di funzionare. Il filtro protegge le
richieste che passano da questo DNS: non è un firewall e non blocca IP diretti,
DNS cifrato, resolver alternativi o aggiornamenti già scaricati. Per isolamento
completo applica anche regole sul router e considera IPv6/DNS annunciati via RA/DHCPv6.
Anche `offline` riguarda le risoluzioni DNS, non tutto il traffico IP della console.
Non esporre il servizio con port forwarding su Internet; è pensato per la LAN.

## Verifica

Sostituisci `192.168.1.10` con `HOST_IP`:

```sh
docker compose ps
dig @192.168.1.10 manuals.playstation.net A +short
# Atteso: 192.168.1.10
dig +tcp @192.168.1.10 manuals.playstation.net A +short
dig @192.168.1.10 manuals.playstation.net AAAA
# Atteso: nessun AAAA
dig @192.168.1.10 feu01.ps5.update.playstation.net A
# Atteso: NXDOMAIN
dig @192.168.1.10 telemetry-console.api.playstation.com AAAA
# Atteso: NXDOMAIN
dig @192.168.1.10 example.org A
# selective: risposta upstream; offline: NXDOMAIN
curl -k --resolve manuals.playstation.net:443:192.168.1.10 \
  https://manuals.playstation.net/document/it/ps5/index.html
curl -I --resolve www.playstation.com:80:192.168.1.10 http://www.playstation.com/
# Atteso: 302 verso https://manuals.playstation.net/
docker compose exec ps5-host python /app/healthcheck.py
```

Test locali senza dipendenze Python esterne:

```sh
python3 -m unittest discover -s tests -v
```

I test DNS reali vengono saltati se `dnsmasq` non è installato. Per eseguirli con
il binario dell'immagine dopo la build, senza pubblicare porte:

```sh
docker run --rm --entrypoint python \
  -v "$PWD/tests:/app/tests:ro" ps5-webkit-autoloader-dns:local \
  -m unittest discover -s /app/tests -v
```

## Aggiornamento e provenienza

Per aggiornare, scegli una release stabile effettivamente pubblicata in `.env` e ricostruisci.
Lo script verifica il tag tramite API GitHub e usa il nome dell'artefatto Python
pubblicato, verificando anche il digest GitHub quando disponibile. Una versione
inesistente causa un errore esplicito: non viene sostituita automaticamente.
L'integrazione gestisce le API HTTP delle release 0.5.2 e 0.6.1.
Non viene
usato un riferimento mobile `latest`. Il digest effettivo e l'URL scaricato sono
in `/app/UPSTREAM.txt`; la licenza upstream è in `/app/LICENSE.upstream`.
Puoi impostare il digest atteso da una fonte verificata in `AUTOLOADER_SHA256`.
Il codice di integrazione non modifica i file frontend/payload della release.
La distribuzione di immagini con il software upstream GPL-3.0 deve rispettarne
la licenza e gli obblighi relativi al codice sorgente corrispondente.

Fonti consultate il 23 ottobre 2026:

- [Release ufficiale v0.6.1 e artefatti](https://github.com/itsPLK/ps5-webkit-autoloader/releases/tag/v0.6.1).
- [Host ufficiale della stessa versione](https://github.com/itsPLK/ps5-webkit-autoloader/blob/v0.6.1/pc-host/host.py): gestione Guida e contenuti incorporati.
- [Configurazione Al-Azif](https://github.com/Al-Azif/ps4-exploit-host/blob/master/settings.json): base dei suffissi PlayStation bloccati e ingressi web.
- [Ricerca sui domini PS5](https://github.com/Yelodress/understanding-ps5-domains): server regionali e telemetria; alcune descrizioni sono dichiarate non verificate dall'autore.
- [Manuale dnsmasq](https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html): zone locali e record statici.
