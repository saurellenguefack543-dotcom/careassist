# CareAssist

Site : **https://getcareassist.com** · Contact : **contact@getcareassist.com**

> **Ne manquez plus jamais un rendez-vous. Votre réceptionniste IA 24/7 pour les professionnels de santé.**

CareAssist est un MVP de SaaS de réceptionniste IA (téléphone + chat) pour cabinets de santé :
**dentistes, psychologues / psychothérapeutes, ophtalmologues, médecins généralistes, kinésithérapeutes**.
Il décroche les appels, prend / déplace / annule les rendez-vous, répond aux questions courantes
(horaires, accès, carte Vitale, tiers payant, mutuelle, C2S…) et **trie les urgences selon la spécialité**
(créneau prioritaire du jour, orientation vers le médecin, ou numéros d'urgence du pays immédiatement).

Chaque cabinet a son **espace** (patients, agenda, appels, messages, sauvegardes), des **rappels automatiques**
patient + praticien, un **numéro VoIP cloud** (Twilio, Vonage, Africa's Talking) et un **profil pays**
(fuseau, téléphone, canaux, urgences locales vérifiées) : France, Sénégal, Côte d'Ivoire, Cameroun…

Offre : **un seul plan, appels illimités pour un cabinet solo ou un petit groupe** — 299 €/mois en Europe (référence),
tarifs régionaux en devise locale pour l'Afrique (prix indicatifs à valider, voir [Tarifs régionaux et paiements](#tarifs-régionaux-et-paiements)).

---

## Sommaire
1. [Contenu du projet](#contenu-du-projet)
2. [Architecture](#architecture)
3. [Démarrage rapide](#démarrage-rapide)
4. [Tester](#tester)
5. [Système de spécialités](#système-de-spécialités)
6. [Brancher un LLM (Groq, OpenAI, Ollama)](#brancher-un-llm)
7. [Téléphonie : Twilio](#téléphonie--twilio)
8. [Téléphonie : Vapi](#téléphonie--vapi)
9. [Alternatives open-source](#alternatives-open-source)
10. [Espace cabinet (multi-tenant) et comptes de démo](#espace-cabinet-multi-tenant)
11. [Adaptation par pays et zone](#adaptation-par-pays-et-zone)
12. [VoIP cloud : appels, SMS, WhatsApp](#voip-cloud--appels-sms-whatsapp)
13. [Notifications et rappels](#notifications-et-rappels)
14. [Sauvegardes et exports](#sauvegardes-et-exports)
15. [Sécurité et RGPD](#sécurité-et-rgpd)
16. [Déploiement (Render, Docker)](#déploiement)
17. [Tarifs régionaux et paiements](#tarifs-régionaux-et-paiements)
18. [Go-to-market et monétisation](#go-to-market-et-monétisation)
19. [Limites du MVP](#limites-du-mvp)

---

## Contenu du projet

```
careassist-mvp/
├── app/
│   ├── main.py              # API FastAPI (chat, créneaux, RDV, leads, admin, pages statiques)
│   ├── engine.py            # moteur de conversation hybride (règles + LLM optionnel)
│   ├── specialties.py       # config par spécialité : types de RDV, FAQ, assurance, urgences, presets ROI
│   ├── emergency.py         # détection d'urgence déterministe (règles communes + spécialité)
│   ├── prompts.py           # prompt système de base + surcouche spécialité
│   ├── llm.py               # client compatible OpenAI (Groq / OpenAI / Ollama)
│   ├── booking.py           # disponibilités, réservation atomique, annulation
│   ├── calendar_adapter.py  # adaptateurs agenda : SQLite, mock Google Calendar, squelette Google
│   ├── voice.py             # webhooks Twilio (TwiML) et Vapi (custom LLM + tool calls)
│   ├── pricing.py           # grille tarifaire par région/devise (prix indicatifs à valider)
│   ├── payments.py          # checkout + webhooks Stripe / Flutterwave / Paystack, mode démo
│   ├── espace.py            # API de l'espace cabinet : auth, patients, agenda, équipe, paramètres, exports
│   ├── auth.py              # bcrypt, sessions serveur, CSRF, rôles
│   ├── security.py          # limitation de débit, en-têtes de sécurité / CSP, journal d'audit
│   ├── countries.py         # profils pays : fuseau, téléphone, canaux, langues, urgences vérifiées (sources)
│   ├── phone.py             # normalisation E.164 (phonenumbers)
│   ├── patients.py          # base patients par cabinet
│   ├── telephony.py         # VoIP : routage par numéro, journal d'appels, messagerie, Vonage, Africa's Talking
│   ├── messaging.py         # envoi SMS / WhatsApp / e-mail (Twilio, Vonage, Africa's Talking, SMTP) + mode démo
│   ├── notifications.py     # confirmations, rappels J-1/H-2, heures de silence, réponses OUI/ANNULER/STOP
│   ├── scheduler.py         # APScheduler : rappels, sauvegardes, créneaux, rétention
│   ├── backup.py            # sauvegarde SQLite à chaud, rotation, restauration
│   ├── retention.py         # purge RGPD des journaux techniques
│   ├── cli.py               # python -m app.cli send-reminders | backup | restore | purge | create-user | seed
│   ├── seed.py              # cabinets de démo FR / Sénégal / Cameroun, comptes, patients et RDV fictifs
│   ├── db.py                # schéma SQLite + migrations légères
│   └── config.py            # variables d'environnement, nom produit, slogan
├── static/
│   ├── index.html, styles.css, app.js   # landing page (FR/EN, démo, ROI, tarif, FAQ, formulaire)
│   ├── admin.html, admin.js             # tableau de bord super-admin /admin
│   ├── espace.html, espace.css, espace.js  # espace cabinet /espace
│   ├── icons.js, favicon.svg            # icônes SVG inline (aucun emoji, aucune dépendance)
│   └── img/                             # photos Pexels optimisées (WebP + JPG) + CREDITS.md
├── tests/                   # pytest : réservation, urgences par spécialité, chat, leads, voix, paiements
├── data/                    # base SQLite (créée au démarrage)
├── .env.example  requirements.txt  Dockerfile  docker-compose.yml  render.yaml  Procfile  pytest.ini
```

## Architecture

```
 Téléphone ─► Twilio (<Gather speech fr-FR>) ─► POST /twilio/voice ─┐
 Téléphone ─► Vapi (STT/TTS) ─► POST /vapi/chat/completions ────────┤
 Site web  ─► démo JS ─► POST /api/chat ────────────────────────────┤
                                                                    ▼
                                         ┌──────────── engine.py ───────────────┐
                                         │ 1. emergency.detect() (toujours)     │
                                         │    règles communes + spécialité      │
                                         │ 2. machine à états RDV / annulation  │──► booking.py ─► SQLite
                                         │    (aucun créneau inventé)           │        └─► calendar_adapter
                                         │ 3. FAQ : LLM (Groq/OpenAI/Ollama)    │            (mock Google)
                                         │    ou règles si pas de clé / erreur  │
                                         └──────────────┬───────────────────────┘
                                                        ▼
                                    SQLite : conversations, messages, urgences, leads ─► /admin
```

Choix clés :
- **Urgences déterministes** : jamais confiées au LLM ; testées unitairement pour chaque spécialité.
- **Transactions déterministes** : le LLM ne peut ni inventer un créneau ni confirmer un RDV.
- **Zéro clé nécessaire** : sans LLM, le moteur de règles assure toute la démo. Avec une clé, le LLM
  rend les réponses ouvertes plus naturelles, avec repli automatique en cas d'erreur.
- **Multi-cabinets** : chaque cabinet (table `practices`) a une spécialité ; l'API prend `practice`
  (slug, id ou spécialité), Twilio/Vapi prennent `?practice=...` dans l'URL du webhook.

## Démarrage rapide

Prérequis : Python 3.10+ (testé avec 3.13).

```bash
cd careassist-mvp
python3 -m venv .venv
source .venv/bin/activate            # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # facultatif : tout fonctionne sans clé
uvicorn app.main:app --reload --port 8000
```

Puis ouvrez :
- http://localhost:8000/ : landing page + démo interactive
- http://localhost:8000/espace : espace cabinet (comptes de démo ci-dessous)
- http://localhost:8000/admin : super-admin (définir `ADMIN_TOKEN`, ou `ADMIN_OPEN=1` en local)
- http://localhost:8000/docs : documentation OpenAPI interactive

La base `data/careassist.db` et les créneaux des 14 prochains jours sont créés automatiquement au
démarrage (`python -m app.seed` pour relancer le seed à la main ; il est idempotent).

La landing page peut aussi être ouverte directement (`static/index.html` en `file://`) : elle tente
alors `http://localhost:8000` et bascule sur des **réponses simulées hors ligne** si le backend est absent.

## Tester

### Suite automatisée
```bash
pytest            # 130 tests : réservation, urgences, conversations, leads, voix, paiements, espace cabinet,
                  # isolation multi-cabinets, notifications, VoIP, sauvegardes, sécurité
```

### curl
```bash
# Conversation de réservation (dentiste), même session_id d'un message à l'autre
curl -s localhost:8000/api/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"demo1","practice":"dentiste","message":"Bonjour, je voudrais un détartrage demain matin"}'
curl -s localhost:8000/api/chat -H 'Content-Type: application/json' -d '{"session_id":"demo1","message":"le premier"}'
curl -s localhost:8000/api/chat -H 'Content-Type: application/json' -d '{"session_id":"demo1","message":"Je m appelle Marie Dupont, 06 12 34 56 78"}'
curl -s localhost:8000/api/chat -H 'Content-Type: application/json' -d '{"session_id":"demo1","message":"oui"}'

# Urgences
curl -s localhost:8000/api/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"u1","practice":"dentiste","message":"J ai la joue gonflée et très mal"}'
curl -s localhost:8000/api/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"u2","practice":"psychologue","message":"Je pense à en finir"}'

# Lead
curl -s localhost:8000/api/leads -H 'Content-Type: application/json' \
  -d '{"practice_name":"Cabinet Dr Martin","email":"dr.martin@example.fr","phone":"01 23 45 67 89","specialty":"dentiste"}'

# Twilio (simulation d'un tour de parole)
curl -s -X POST 'localhost:8000/twilio/voice?practice=generaliste' -d CallSid=CA1 -d 'SpeechResult=Je voudrais un rendez-vous demain'

# Tarifs et paiement (mode démo sans clé)
curl -s 'localhost:8000/api/pricing?country=SN'
curl -s localhost:8000/api/checkout -H 'Content-Type: application/json' \
  -d '{"region":"europe","practice_name":"Cabinet Dr Martin","email":"dr.martin@example.fr"}'
curl -s localhost:8000/api/checkout -H 'Content-Type: application/json' \
  -d '{"country":"SN","practice_name":"Clinique Dentaire Dakar","email":"contact@example.sn"}'
# -> ouvrir checkout_url (page « MODE DÉMO ») et cliquer « Simuler un paiement réussi »

# Autres
curl -s 'localhost:8000/api/slots?practice=ophtalmologue&limit=3'
curl -s 'localhost:8000/api/prompt?practice=psychologue'     # prompt système complet
curl -s localhost:8000/api/admin/stats -H "X-Admin-Token: $ADMIN_TOKEN"

# Espace cabinet (cookie + jeton CSRF)
curl -s -c jar -X POST localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"dr.martin@demo.getcareassist.com","password":"CareAssist-Demo-2026"}'
curl -s -b jar localhost:8000/api/espace/dashboard
curl -s -b jar 'localhost:8000/api/espace/export?format=csv' -o export.zip
# écritures (POST/PUT/DELETE) : ajouter -H "X-CSRF-Token: $(awk '/ca_csrf/{print $7}' jar)"
```

### Dans le navigateur
Section **Démo** : choisissez une spécialité, cliquez sur un exemple (réservation, remboursement,
urgence) ou tapez librement. Les badges « Urgence vitale », « Urgence prioritaire » et « Rendez-vous
confirmé » s'affichent selon la réponse. Le résultat apparaît en direct dans `/admin`.

## Système de spécialités

Tout est dans `app/specialties.py`, une entrée par spécialité :

| Clé | Durée créneau | Exemples d'urgences gérées |
|---|---|---|
| `dentiste` | 30 min (+ créneaux urgence réservés) | gonflement, dent cassée/expulsée, saignement, rage de dents → créneau du jour ; gonflement du cou / gêne pour avaler → 15 |
| `psychologue` | 60 min | idées suicidaires → **3114 + 15** immédiatement, ton empathique, aucune thérapie ; violences → 17/112/3919 ; crise d'angoisse → premier créneau + 3114 |
| `ophtalmologue` | 20 min (+ urgences) | projection chimique (rinçage 15 min + 15), perte brutale de vision, voile/rideau → 15 ; éclairs/corps flottants, traumatisme, œil rouge douloureux → créneau du jour |
| `generaliste` | 20 min (+ urgences) | douleur thoracique, AVC, fièvre du nourrisson, purpura → 15 ; fièvre, infection… → soins du jour ; hors horaires → 116 117 |
| `kinesitherapeute` | 30 min | signaux post-op (mollet gonflé/chaud, cicatrice infectée, fièvre, déficit neurologique) → orientation chirurgien/médecin le jour même, sans séance ; essoufflement brutal → 15 |

Règles **communes à toutes les spécialités** : détresse respiratoire, perte de connaissance, douleur
thoracique, signes d'AVC, hémorragie, allergie grave (→ 15/112) et idées suicidaires (→ 3114 + 15).

Chaque spécialité définit aussi : types de rendez-vous et durées, notes assurance/remboursement,
discours sur les tarifs (jamais de prix inventé), FAQ spécifiques, conseils d'attente, **surcouche du
prompt système**, exemples de démo et préréglage du calculateur ROI.

**Ajouter une spécialité** (ex. orthophoniste, sage-femme, dermatologue) : ajoutez une entrée dans
`SPECIALTIES`, un cabinet dans `seed.PRACTICES`, ajoutez la spécialité dans `static/app.js` (`SPECS`) et des
cas dans `tests/test_emergency.py`.

> Les informations de remboursement sont volontairement génériques : faites-les valider et
> personnaliser par chaque cabinet avant la mise en production.

## Brancher un LLM

Sans configuration, le moteur de règles répond à tout. Pour des réponses ouvertes plus naturelles :

**Groq** (rapide, offre gratuite pour tester) : créez une clé sur https://console.groq.com puis dans `.env` :
```
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
```
**OpenAI ou tout endpoint compatible** :
```
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```
Vérifiez avec `curl localhost:8000/health` (`"llm": "groq"` ou `"openai-compatible"`). Le champ `engine`
de chaque réponse `/api/chat` indique `rules` ou `llm:<fournisseur>`. Le prompt utilisé est visible
via `GET /api/prompt?practice=<spécialité>`.

## Téléphonie : Twilio

1. Lancez le serveur puis exposez-le : `ngrok http 8000` → `https://xxxx.ngrok-free.app`.
2. Console Twilio → *Phone Numbers* → votre numéro → *Voice Configuration* →
   **A call comes in** : Webhook `https://xxxx.ngrok-free.app/twilio/voice?practice=dentiste`, méthode **HTTP POST**.
3. Appelez le numéro. La boucle est : `<Gather input="speech" language="fr-FR">` → reconnaissance
   vocale Twilio → moteur CareAssist → `<Say voice="Polly.Lea">` → nouveau `<Gather>`.
4. Options `.env` : `HUMAN_TRANSFER_NUMBER=+331...` (transfert `<Dial>` sur demande d'humain ou urgence
   vitale), `TWILIO_VOICE`, et en production `TWILIO_VALIDATE=true` + `TWILIO_AUTH_TOKEN` +
   `PUBLIC_BASE_URL` (vérification de la signature `X-Twilio-Signature`).
5. Côté cabinet : renvoi d'appel (sur non-réponse ou permanent) de la ligne existante vers le numéro Twilio.

Un numéro français Twilio nécessite un dossier réglementaire (justificatif d'adresse) : comptez quelques jours.

## Téléphonie : Vapi

Vapi gère la voix (STT, TTS, interruptions) ; CareAssist fournit l'intelligence métier. Deux modes :

**A. Custom LLM (recommandé)** : Assistant → *Model* → *Custom LLM* →
URL `https://xxxx.ngrok-free.app/vapi?practice=dentiste` (Vapi appelle `/vapi/chat/completions`,
format OpenAI, streaming SSE supporté). Urgences et réservations passent par le moteur déterministe.
Choisissez un transcriber et une voix français (ex. Deepgram `fr`, voix ElevenLabs / Azure fr-FR).

**B. Outils (function calling)** : gardez le LLM de Vapi, collez le prompt de `GET /api/prompt?practice=...`,
réglez la *Server URL* sur `https://xxxx.ngrok-free.app/vapi/webhook?practice=dentiste` et déclarez les outils :
- `check_availability` `{date?: "YYYY-MM-DD", period?: "matin"|"apres-midi"|"soir", limit?: int}`
- `book_appointment` `{slot_id: int, patient_name: string, phone: string, reason?: string, urgent?: bool}`
- `cancel_appointment` `{phone: string}`
- `detect_emergency` `{text: string}`

Le webhook répond au format `{"results":[{"toolCallId": "...", "result": "..."}]}` et accepte aussi
l'ancien format `function-call` ; `end-of-call-report` enregistre le résumé dans le journal.
Secret optionnel : `VAPI_SECRET` (en-tête `x-vapi-secret`). *Ce stub suit le format documenté par Vapi
au moment de l'écriture ; vérifiez la doc Vapi en vigueur lors de l'intégration.*

## Alternatives open-source

- **LLM local** : [Ollama](https://ollama.com) (`ollama run llama3.1` ou `mistral`), puis
  `OPENAI_BASE_URL=http://localhost:11434/v1`, `OPENAI_API_KEY=ollama`, `OPENAI_MODEL=llama3.1`.
  LM Studio et vLLM exposent la même API.
- **Reconnaissance vocale** : Whisper / faster-whisper (bon niveau en français).
- **Synthèse vocale** : Piper (voix `fr_FR`), ou Coqui XTTS.
- **Téléphonie** : Asterisk / FreeSWITCH + un opérateur SIP, ou des frameworks d'agents vocaux
  temps réel (Pipecat, LiveKit Agents) qui orchestrent STT → `/vapi/chat/completions` (format OpenAI) → TTS.

Ce MVP s'inspire de l'esprit de projets open-source de réceptionnistes vocaux (call-assist,
Dental-Voice-Assistant, open-receptionist, Aiva) : boucle STT → LLM → TTS, prise de rendez-vous par
outils, journalisation. Il a été réécrit et simplifié ici, sans reprise de leur code.

## Espace cabinet (multi-tenant)

Chaque cabinet dispose de **son propre espace** sur `/espace` : base patients, agenda, journal d'appels et de
messages, notifications, équipe, horaires, paramètres, exports et sauvegardes. Toutes les requêtes de l'espace
sont filtrées par `practice_id` côté serveur (le cabinet vient de la session, jamais du client) : un cabinet ne
peut ni lire ni modifier les données d'un autre (tests `tests/test_espace.py::test_tenant_isolation*`).

| Rôle | Droits |
|---|---|
| `owner` (titulaire) | tout, dont équipe, utilisateurs, horaires, paramètres, suppression RGPD d'un patient, journal d'audit |
| `practitioner` | patients, agenda, appels/messages, notifications |
| `secretary` (secrétariat) | idem praticien + export du cabinet ; pas de paramètres ni de suppression |

- **Authentification** : mots de passe bcrypt (≥ 10 caractères, lettres + chiffres), session serveur de 12 h
  (cookie `ca_session` HttpOnly, SameSite=Lax, Secure en HTTPS ; seul un hash SHA-256 du jeton est stocké),
  protection CSRF double-submit (cookie `ca_csrf` + en-tête `X-CSRF-Token`), limitation des tentatives de connexion
  (par IP et par e-mail), changement de mot de passe (`POST /api/auth/password`, révoque les autres sessions).
- **Patients** : création/modification/recherche (insensible aux accents), canal préféré (SMS / WhatsApp / e-mail),
  consentement aux messages (et `STOP` par SMS), historique RDV / appels / messages / notifications,
  **export RGPD** (JSON) et **suppression RGPD** (anonymisation de l'historique lié).
- **Agenda** : vue semaine et vue liste ; statuts `confirmed`, `reminded`, `honored`, `no_show`, `cancelled` ;
  création, déplacement sur un créneau libre, annulation (avec notifications).
- **Inscription** d'un nouveau cabinet : formulaire « Créer l'espace de mon cabinet » (pays, spécialité, fuseau
  déduit du pays) → cabinet, titulaire, praticien, horaires par défaut et créneaux sur 14 jours.
- `/admin` reste la vue **super-admin** (tous cabinets), protégée par `ADMIN_TOKEN`.

### Comptes de démo
Mot de passe commun : **`CareAssist-Demo-2026`** (comptes fictifs créés par le seed, `SEED_DEMO=1`).

| E-mail | Rôle | Cabinet |
|---|---|---|
| `dr.martin@demo.getcareassist.com` | titulaire | Cabinet dentaire du Parc (Paris, FR) |
| `accueil.parc@demo.getcareassist.com` | secrétariat | Cabinet dentaire du Parc |
| `dr.benali@demo.getcareassist.com` | praticien | Cabinet dentaire du Parc |
| `dr.diop@demo.getcareassist.com` | titulaire | Cabinet médical des Almadies (Dakar, SN) |
| `dr.ngono@demo.getcareassist.com` | titulaire | Cabinet dentaire de Bonapriso (Douala, CM) |

> Désactivez `SEED_DEMO` (ou changez ces mots de passe) avant toute mise en production réelle.

## Adaptation par pays et zone

`app/countries.py` contient un **profil par pays** : fuseau horaire, indicatif et format E.164 (validation avec
`phonenumbers`), devise (issue de la grille `pricing.py`), canaux préférés (Afrique : WhatsApp puis SMS ; Europe :
SMS puis e-mail), langues (fr/en, extensible), formats de date/heure, documents à apporter et **numéros d'urgence**.
Le prompt système de l'IA, les réponses d'urgence et les messages vocaux utilisent le profil du cabinet
(jetons `[[SAMU]]`, `[[POLICE]]`, `[[SUICIDE]]`… remplacés à la volée). Les rendez-vous sont stockés en heure locale
du cabinet, les envois planifiés en UTC.

**Règle** : un numéro d'urgence n'est intégré que s'il est vérifié sur une source officielle ou fiable ; sinon le
pays est marqué `TODO` et l'IA renvoie vers « les services d'urgence locaux » sans inventer de numéro.

| Pays | Urgences intégrées | Sources |
|---|---|---|
| France | SAMU 15, 112, police 17, pompiers 18, prévention suicide 3114, sourds/malentendants 114, violences 3919, permanence de soins 116 117 | service-public.gouv.fr (F33954), masecurite.interieur.gouv.fr, solidarites.gouv.fr |
| Sénégal | SAMU 1515, police 17, pompiers 18 | sante.gouv.sn, samu.sn, policenationale.gouv.sn, sapeurspompiers.gouv.sn |
| Côte d'Ivoire | SAMU 185, pompiers 180, police 110 / 111 / 170 | orange.ci (numéros utiles), ci.diplomatie.gouv.fr |
| Cameroun | SAMU 119, police 117, pompiers 118 | minat.gov.cm, yaounde.consulfrance.org |
| Maroc, Nigeria, Kenya, Ghana, Belgique | **TODO** (non vérifiés, non intégrés) | — |

Pas de ligne nationale de prévention du suicide vérifiée pour SN / CI / CM (TODO). Les URL exactes figurent dans
`app/countries.py`. **Faites relire ces numéros localement avant toute mise en service.**

Ajouter un pays : une entrée dans `COUNTRIES` (+ `pricing.COUNTRY_REGION` pour la devise) et un test.

## VoIP cloud : appels, SMS, WhatsApp

Chaque cabinet a **son numéro** (`voip_number`, E.164, unique) et son fournisseur (`twilio`, `vonage`,
`africastalking`, ou `auto` : Africa's Talking pour KE/UG/TZ/RW/MW/ZM/NG/ET, sinon Twilio). Les appels et SMS
entrants sont **routés vers le bon cabinet d'après le numéro appelé**. Chaque appel est journalisé (durée,
statut, transcription des tours de parole, patient reconnu) et visible dans l'espace.

- **Appel manqué / silence** : messagerie vocale (enregistrement), puis **SMS automatique** proposant un rappel ou
  la prise de RDV par message (une seule fois par numéro et par jour).
- **Transfert humain** : sur demande ou urgence vitale, vers `transfer_number` du cabinet (`HUMAN_TRANSFER_NUMBER` par défaut).
- **Mode démo** : sans clé (ou `MESSAGING_MODE=mock`), aucun appel réseau ; les messages sont enregistrés avec le
  statut `mock_sent`. Les cabinets de démo n'envoient jamais en réel, même avec des clés (sauf `DEMO_LIVE_MESSAGING=1`).

| Fournisseur | Variables | Webhooks à configurer |
|---|---|---|
| Twilio (voix, SMS, WhatsApp) | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM` ou `TWILIO_MESSAGING_SERVICE_SID`, `TWILIO_WHATSAPP_FROM` | Voix : `POST /twilio/voice` ; statut d'appel : `/twilio/status` ; SMS/WhatsApp entrants : `/twilio/sms`. Signature `X-Twilio-Signature` vérifiée si `TWILIO_VALIDATE=true` |
| Vonage (Voice API NCCO + SMS API) | `VONAGE_API_KEY`, `VONAGE_API_SECRET`, `VONAGE_FROM` | Answer URL : `/vonage/answer?wt=…` ; Event URL : `/vonage/event?wt=…` ; SMS entrants : `/vonage/inbound-sms?wt=…` |
| Africa's Talking (voix + SMS) | `AT_USERNAME` (`sandbox` pour tester), `AT_API_KEY`, `AT_SENDER_ID` | Voix : `/africastalking/voice?wt=…` ; SMS entrants : `/africastalking/sms?wt=…` |
| E-mail | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | — |

`wt` = valeur de `VOIP_WEBHOOK_TOKEN` (jeton partagé, car Africa's Talking ne signe pas ses webhooks ; pour Vonage,
les webhooks signés JWT sont recommandés en production). État de la configuration : `GET /api/voip/status`.

Formats d'API utilisés (non testés contre les API réelles, aucune clé disponible) : Twilio
`POST /2010-04-01/Accounts/{sid}/Messages.json` ; Vonage `POST https://rest.nexmo.com/sms/json` ;
Africa's Talking `POST https://api.africastalking.com/version1/messaging` (`api.sandbox…` en sandbox, en-tête `apiKey`).

**SIP générique (Asterisk / FreeSWITCH)** : pour utiliser votre propre opérateur SIP, deux options :
(1) faire pointer un trunk SIP vers Twilio *Elastic SIP Trunking* ou Vonage *SIP* : CareAssist reçoit alors les
mêmes webhooks ; (2) dans Asterisk, un dialplan `AGI`/`ARI` (ou FreeSWITCH `mod_httapi`) qui transcrit (Whisper),
appelle `POST /api/chat` avec `practice` = cabinet du numéro appelé et `session_id` = identifiant d'appel, puis lit la
réponse (Piper TTS). Non fourni clé en main dans ce MVP.

## Notifications et rappels

À chaque rendez-vous, **le patient et le praticien sont prévenus** :
- **confirmation** à la réservation (patient + praticien) ;
- **rappels** patient à **J-1 et H-2** par défaut, praticien à H-2 (délais configurables par cabinet dans Paramètres) ;
- **annulation** notifiée aux deux.

Canal : préférence du patient s'il y a consentement, sinon canaux par défaut du pays (WhatsApp/SMS en Afrique,
SMS/e-mail en Europe). Les réponses entrantes sont comprises : **OUI** (confirme), **NON / ANNULER** (annule et libère
le créneau), **RAPPEL** (demande de rappel), **STOP** (retire le consentement) ; tout autre texte est traité par l'IA.

Garanties : envoi **idempotent** (clé unique par RDV, horaire, destinataire et type ; réclamation atomique avant
envoi, donc jamais deux fois même avec plusieurs workers), respect du **fuseau du cabinet** et des **heures de
silence** (21:00–08:00 par défaut, envoi reporté), rappels déjà passés ignorés, journal visible dans l'espace.

Exécution : APScheduler dans le processus web (`SCHEDULER_ENABLED=1`, toutes les `REMINDER_INTERVAL_S` secondes),
**ou** cron avec `SCHEDULER_ENABLED=0` :
```
* * * * *   cd /app && python -m app.cli send-reminders
0 3 * * *   cd /app && python -m app.cli backup
45 3 * * *  cd /app && python -m app.cli purge
```

## Sauvegardes et exports

- **Export du cabinet** (titulaire, secrétariat) depuis l'espace : JSON complet ou archive ZIP de CSV
  (protégés contre l'injection de formules tableur). Export RGPD par patient.
- **Sauvegarde quotidienne** de la base SQLite (API de sauvegarde à chaud de sqlite3, fichiers `chmod 600`),
  rotation (`BACKUP_KEEP`, 7 par défaut) dans `BACKUP_DIR` (`data/backups` par défaut).
```bash
python -m app.cli backup --keep 7
python -m app.cli list-backups
python -m app.cli restore data/backups/careassist-<horodatage>.db   # vérifie l'intégrité, garde une copie de l'actuelle
python -m app.cli create-user <practice_id> secretariat@cabinet.fr "Accueil" secretary   # mot de passe demandé
```
Copiez les sauvegardes **hors du serveur** (stockage objet chiffré, autre région) : une sauvegarde sur le même
disque ne protège pas d'une perte du disque.

**PostgreSQL / `DATABASE_URL`** : non implémenté. Le code utilise `sqlite3` directement (SQL standard, quelques
`INSERT OR IGNORE` / `ALTER TABLE` spécifiques). Migration recommandée avant plusieurs centaines de cabinets ou
plusieurs instances : introduire SQLAlchemy Core (ou psycopg) derrière `db.get_conn()`, remplacer `INSERT OR IGNORE`
par `ON CONFLICT DO NOTHING`, puis migrer les données (`pgloader`). Les sauvegardes passent alors par `pg_dump`.

**Hébergement HDS** : en France, héberger des données de santé pour le compte de tiers impose un hébergeur
**certifié HDS** (OVHcloud, Scaleway, Outscale, régions certifiées d'Azure/AWS/GCP…). Render, Railway et Fly.io ne le
sont pas : utilisez-les pour la démo uniquement. Dans les autres pays, vérifiez la loi locale (ex. Sénégal : CDP).

## Sécurité et RGPD

- **Accès** : `/admin` fermé par défaut (401 sans `ADMIN_TOKEN`, comparaison en temps constant, jeton en en-tête et
  `sessionStorage`, jamais dans l'URL) ; espace cabinet avec rôles et isolation stricte ; CSRF sur toutes les écritures.
- **Limitation de débit** (mémoire, par IP) : connexion, inscription, chat, leads, paiement, webhooks entrants, API espace.
  Derrière un proxy : `TRUST_PROXY=1`. Plusieurs instances : déplacer le compteur dans Redis.
- **En-têtes** : Content-Security-Policy, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`,
  HSTS en HTTPS, `Cache-Control: no-store` sur les API privées ; CORS restreint (`CORS_ORIGINS`), `/docs` désactivable.
- **Webhooks** : signatures Stripe / Paystack / Flutterwave / Twilio, jeton partagé Vonage / Africa's Talking,
  `VAPI_SECRET` pour Vapi (à définir obligatoirement en production).
- **Secrets** : uniquement par variables d'environnement (`.env` ignoré par git, test anti-secret en dur).
- **RGPD** : consentement aux messages par patient (`STOP`), export et suppression par patient, export du cabinet,
  **journal d'audit** (identifiants uniquement, aucune donnée de santé), purge automatique des journaux techniques
  après `RETENTION_DAYS` (3 ans par défaut, à aligner sur votre politique), sessions expirées purgées. Les journaux
  applicatifs ne contiennent pas de contenu de message.
- **Sécurité IA** : urgences détectées de façon déterministe avant tout LLM (jamais confiées au modèle), numéros
  d'urgence non vérifiés jamais affichés, le LLM ne peut ni inventer un créneau ni confirmer un RDV.

## Déploiement

**Render (un clic)** : le fichier `render.yaml` décrit un *Blueprint* : Render → *New* → *Blueprint* → choisissez
le dépôt GitHub. Service web Python gratuit, `healthCheckPath: /health`, `ADMIN_TOKEN` et `VOIP_WEBHOOK_TOKEN`
générés automatiquement, clés fournisseurs à saisir dans le dashboard (`sync: false`).
> **Persistance** : le plan gratuit n'a **pas de disque persistant** : la base SQLite est réinitialisée à chaque
> redéploiement ou mise en veille prolongée (acceptable pour une démo, pas pour des patients). En production, passez
> en plan payant et activez le bloc `disk` du `render.yaml` (`DB_PATH=/var/data/careassist.db`,
> `BACKUP_DIR=/var/data/backups`), ou utilisez PostgreSQL. Le plan gratuit se met en veille : le planificateur de
> rappels ne tourne pas pendant la veille (préférez un plan payant ou un cron externe).

**Procfile** (Heroku, Scalingo, Clever Cloud…) : `web: uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers`.
Scalingo et Clever Cloud proposent des offres certifiées HDS.

**Docker**
```bash
cp .env.example .env
docker compose up -d --build        # http://localhost:8000, base persistée dans ./data ; HEALTHCHECK sur /health
```
**Domaine** : `getcareassist.com` → définissez `PUBLIC_BASE_URL=https://getcareassist.com`, puis configurez les
webhooks Twilio / Vonage / Africa's Talking / Vapi / paiement sur ce domaine.

**Railway** / **Fly.io** : `Dockerfile` détecté ; montez un volume sur `/app/data`.

Check-list production : `ADMIN_TOKEN`, `COOKIE_SECURE=true`, `TRUST_PROXY=1`, `TWILIO_VALIDATE=true`,
`VOIP_WEBHOOK_TOKEN`, `VAPI_SECRET`, secrets de webhooks paiement, `SEED_DEMO=0`, `DISABLE_DOCS=1`,
un seul processus avec `SCHEDULER_ENABLED=1` (ou cron), sauvegardes copiées hors serveur, hébergement HDS.

## Tarifs régionaux et paiements

Un seul plan par région (appels illimités, cabinet solo ou petit groupe), facturé chaque mois dans la
devise locale. La grille est dans `app/pricing.py` ; elle peut être remplacée sans toucher au code via
`PRICING_FILE=/chemin/pricing.json` (mêmes clés, ex. `{"uemoa": {"amount": 49000}}`).

> **Prix indicatifs à valider.** Seul le tarif Europe (299 EUR/mois HT) est la référence. Les autres
> montants sont des **exemples par défaut**, ajustés grossièrement au pouvoir d'achat local : ce ne sont
> ni des conversions de change exactes ni des prix validés. Les équivalents en euros sont approximatifs
> (sauf XOF/XAF, à parité fixe 655,957 pour 1 EUR). Validez-les (marché, TVA/fiscalité locale, frais des
> prestataires) avant de commercialiser.

| Région (clé) | Pays | Prix par défaut / mois | ≈ EUR | Prestataire | Moyens de paiement |
|---|---|---|---|---|---|
| Europe (`europe`) | zone euro, Monaco | **299 EUR (référence)** | 299 | Stripe | carte, prélèvement SEPA |
| International (`international`) | US, CA, GB, CH, autres hors Afrique | 329 USD | ~299 | Stripe | carte |
| UEMOA (`uemoa`) | SN, CI, ML, BF, BJ, TG, NE, GW | 59 000 XOF | 90 | Flutterwave | carte, Orange Money, MTN MoMo, Moov, Wave (selon pays) |
| CEMAC (`cemac`) | CM, GA, CG, TD, CF, GQ | 59 000 XAF | 90 | Flutterwave | carte, Orange Money, MTN MoMo (selon pays) |
| Nigeria (`nigeria`) | NG | 95 000 NGN | ~55 | Paystack | carte, virement, USSD |
| Ghana (`ghana`) | GH | 900 GHS | ~60 | Paystack | carte, MTN MoMo, Telecel Cash, AirtelTigo |
| Kenya (`kenya`) | KE | 8 500 KES | ~60 | Paystack | carte, M-Pesa, Airtel Money |
| Afrique du Sud (`south_africa`) | ZA | 1 990 ZAR | ~100 | Paystack | carte, EFT |
| Maroc (`morocco`) | MA | 1 290 MAD | ~120 | Stripe | carte |
| Maghreb (`maghreb`) | DZ, TN, MR | 129 EUR | 129 | Stripe | carte internationale |
| Autres pays d'Afrique (`africa_other`) | CD, GN, MG, RW, UG, TZ, EG… | 99 USD | ~90 | Flutterwave | carte |

Sur la landing page, la section Tarif propose un sélecteur pays/région, pré-rempli à partir du fuseau
horaire et de la langue du navigateur (`Africa/Dakar` → UEMOA, `fr-SN` → UEMOA…) et modifiable à la main
(choix mémorisé). Le prix du hero et le calculateur ROI suivent la région choisie.

### Parcours de paiement
1. `POST /api/checkout` `{region | country, practice_name, email, phone?, specialty?}` → crée un abonnement
   `pending` dans SQLite (table `subscriptions`) et renvoie `checkout_url`.
2. Le client paie sur la page hébergée du prestataire (Stripe Checkout, Flutterwave Standard, Paystack).
3. Le prestataire appelle le webhook → l'abonnement passe `active` (visible dans `/admin`, onglet Abonnements).

**Mode démo (par défaut, aucune clé)** : la réponse contient `"mode": "mock"` et un avertissement, et
`checkout_url` pointe vers `/checkout/mock/<ref>`, une page clairement marquée « MODE DÉMO — aucun paiement
réel » avec un bouton « Simuler un paiement réussi ». Forcer la démo même avec des clés : `PAYMENTS_MODE=mock`.

### Configuration des prestataires (variables `.env`, aucune clé dans le code)
- **Stripe** (Europe, international, Maroc, Maghreb) : `STRIPE_SECRET_KEY` (sk_test_… pour tester).
  Appel `POST /v1/checkout/sessions` en `mode=subscription` avec `price_data` récurrent mensuel
  (ou `STRIPE_PRICE_<REGION>` pour un prix créé dans le dashboard). Activez SEPA dans le dashboard.
  Webhook : `https://getcareassist.com/webhooks/stripe`, événements `checkout.session.completed`,
  `customer.subscription.deleted`, `invoice.payment_failed` ; secret `STRIPE_WEBHOOK_SECRET` (whsec_…),
  vérification de l'en-tête `Stripe-Signature` (HMAC-SHA256, tolérance 5 min).
- **Flutterwave** (UEMOA, CEMAC, autres pays d'Afrique) : `FLW_SECRET_KEY`. Appel `POST /v3/payments`
  (Flutterwave Standard) avec `tx_ref`, `amount`, `currency`, `payment_options` (`card,mobilemoneyfranco`…) ;
  paiement récurrent via `FLW_PLAN_<REGION>` (`payment_plan`). Webhook : `https://getcareassist.com/webhooks/flutterwave`,
  « secret hash » du dashboard dans `FLW_SECRET_HASH` (en-tête `verif-hash`), puis vérification de la
  transaction par `GET /v3/transactions/{id}/verify` (statut, montant, devise).
- **Paystack** (Nigeria, Ghana, Kenya, Afrique du Sud) : `PAYSTACK_SECRET_KEY`. Appel
  `POST /transaction/initialize` (montant en sous-unité : kobo, pesewas, cents) avec `channels`
  (`card`, `mobile_money`, `bank`, `ussd`, `eft`…) ; abonnement via `PAYSTACK_PLAN_<REGION>` (`plan`).
  Webhook : `https://getcareassist.com/webhooks/paystack`, signature `x-paystack-signature`
  (HMAC-SHA512 du corps avec la clé secrète).

Sécurité : sans secret de webhook configuré, seuls les événements visant un abonnement en mode démo sont
acceptés ; tout événement visant un abonnement réel est refusé.

Disponibilité : les moyens de paiement réellement proposés dépendent du pays, de la devise et de
l'activation de votre compte chez chaque prestataire (ex. Wave, Orange Money). Vérifiez dans leur dashboard.

## Go-to-market et monétisation

- **Un seul plan par région** : 299 €/mois HT en Europe, prix locaux en Afrique (indicatifs à valider),
  appels illimités, cabinet solo ou petit groupe, sans engagement. Le mobile money (Orange Money, MTN MoMo,
  M-Pesa, Wave selon pays) lève le principal frein au paiement récurrent pour les cabinets africains.
  Le calculateur ROI de la landing page montre qu'un ou deux nouveaux patients récupérés par mois suffisent
  souvent à rentabiliser l'abonnement (selon la spécialité et les hypothèses saisies).
- **Coûts variables** à surveiller : minutes Twilio/Vapi + LLM. Fixez un plafond « usage raisonnable »
  dans les CGV et suivez le coût par cabinet.
- **Acquisition** : démarchage ciblé (annuaires publics de professionnels de santé, Google Maps), démo
  personnalisée en 24 h avec le nom du cabinet (le seed se duplique facilement), partenariats avec
  intégrateurs informatiques de cabinets, prothésistes, centres de formation, associations professionnelles.
- **Pilote** : 14 jours d'essai sur renvoi « non-réponse » uniquement, puis bilan chiffré
  (appels décrochés, RDV pris, urgences orientées) depuis `/admin`.
- **Upsell** futur : SMS de rappel, intégration logiciel métier, multi-sites (sur devis).

## Limites du MVP

- Démo : cabinets, praticiens, patients et créneaux fictifs. SMS / WhatsApp / e-mails / appels en **mode démo**
  (enregistrés, non envoyés) : les intégrations Twilio, Vonage, Africa's Talking et SMTP suivent les formats d'API
  documentés mais n'ont pas été testées avec de vraies clés.
- SQLite uniquement (pas de `DATABASE_URL` PostgreSQL) ; limitation de débit en mémoire (une seule instance).
- Urgences : numéros vérifiés pour FR, SN, CI, CM seulement ; autres pays en TODO. Profils et modèles de messages
  en français (anglais partiel).
- Pas de double authentification (2FA) ni de réinitialisation de mot de passe par e-mail ; pas de chiffrement
  applicatif de la base (s'appuyer sur le chiffrement disque de l'hébergeur HDS).
- Compréhension par règles (sans LLM) : formulations simples ; la sélection de créneau attend
  « le premier / 2 / 10h30 ». Les dates absolues (« le 14 mars ») ne sont pas encore comprises.
- Identification pour annulation par numéro de téléphone uniquement (prévoir une vérification renforcée).
- Google Calendar : adaptateur simulé (`data/mock_google_calendar.jsonl`) ; la vraie intégration est à
  compléter dans `GoogleCalendarAdapter`.
- Paiements : testés en mode démo et avec des réponses de prestataires simulées ; aucun appel réel n'a été fait
  aux API Stripe/Flutterwave/Paystack. Renouvellements mensuels : Stripe gère l'abonnement nativement ;
  pour Flutterwave/Paystack, configurez un plan (`FLW_PLAN_*`, `PAYSTACK_PLAN_*`), sinon seul le premier mois est encaissé.
  Pas de facturation/TVA automatique, ni de gestion des impayés au-delà du statut `failed`.
- CareAssist n'est pas un dispositif médical : il oriente et organise, il ne diagnostique pas.
  Les règles d'urgence et les textes de remboursement doivent être relus par des professionnels.

Contact : contact@getcareassist.com · https://getcareassist.com

Crédits photos : voir `static/img/CREDITS.md` (Pexels, licence Pexels).
