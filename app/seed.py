"""Données de démo : un cabinet par spécialité (France) + un cabinet au Sénégal et un au Cameroun, leurs praticiens,
horaires, créneaux (14 jours), comptes de démo, patients fictifs et quelques rendez-vous avec notifications.

Les numéros de téléphone sont FICTIFS (France : plage 01 99 00 xx xx réservée à la fiction par l'ARCEP). Les cabinets de
démo (is_demo=1) ne déclenchent jamais d'envoi réel, même si des clés VoIP sont configurées (voir messaging.py).
"""
import json
from datetime import date, datetime, time, timedelta

from . import db
from .specialties import SPECIALTIES

DEMO_PASSWORD = "CareAssist-Demo-2026"

PRACTICES = [
    {"slug": "dentiste", "name": "Cabinet Dentaire du Parc", "specialty": "dentiste",
     "address": "12 avenue de la République, 75011 Paris", "phone": "01 23 45 67 89",
     "hours": "du lundi au vendredi de 9h à 12h30 et de 14h à 19h, le samedi de 9h à 13h",
     "access": "Métro Oberkampf, parking public à 100 m, accessible PMR",
     "ranges": {"week": [(time(9), time(12, 30)), (time(14), time(19))], "sat": [(time(9), time(13))]},
     "emergency_times": [time(11, 30), time(12), time(17, 30), time(18)],
     "practitioners": [("Dr Claire Martin", "Soins & urgences"), ("Dr Karim Benali", "Implantologie & prothèses")]},
    {"slug": "psychologue", "name": "Cabinet de Psychologie Les Tilleuls", "specialty": "psychologue",
     "address": "4 rue des Tilleuls, 69006 Lyon", "phone": "04 12 34 56 78",
     "hours": "du lundi au vendredi de 8h à 20h, le samedi de 9h à 13h",
     "access": "Métro Foch, cabinet au rez-de-chaussée",
     "ranges": {"week": [(time(8), time(20))], "sat": [(time(9), time(13))]},
     "emergency_times": [],
     "practitioners": [("Mme Julie Moreau", "Psychologue clinicienne"), ("M. Thomas Girard", "Psychothérapeute — couples & adolescents")]},
    {"slug": "ophtalmologue", "name": "Centre Ophtalmologique Vision Plus", "specialty": "ophtalmologue",
     "address": "28 cours de l'Intendance, 33000 Bordeaux", "phone": "05 12 34 56 78",
     "hours": "du lundi au vendredi de 8h30 à 12h et de 13h30 à 18h30",
     "access": "Tram B Gambetta, accessible PMR",
     "ranges": {"week": [(time(8, 30), time(12)), (time(13, 30), time(18, 30))], "sat": []},
     "emergency_times": [time(11, 10), time(11, 30), time(17, 50), time(18, 10)],
     "practitioners": [("Dr Hélène Dubois", "Ophtalmologie générale & urgences"), ("Dr Marc Petit", "Glaucome & cataracte")]},
    {"slug": "generaliste", "name": "Cabinet Médical Saint-Michel", "specialty": "generaliste",
     "address": "7 place Saint-Michel, 13001 Marseille", "phone": "04 91 23 45 67",
     "hours": "du lundi au vendredi de 8h à 12h et de 14h à 19h, le samedi de 9h à 12h",
     "access": "Métro Noailles, parking rue Longue",
     "ranges": {"week": [(time(8), time(12)), (time(14), time(19))], "sat": [(time(9), time(12))]},
     "emergency_times": [time(11, 20), time(11, 40), time(18, 20), time(18, 40)],
     "practitioners": [("Dr Paul Lefèvre", "Médecine générale"), ("Dr Amina Haddad", "Médecine générale & pédiatrie")]},
    {"slug": "kinesitherapeute", "name": "Kiné Santé Nantes", "specialty": "kinesitherapeute",
     "address": "15 quai de la Fosse, 44000 Nantes", "phone": "02 40 12 34 56",
     "hours": "du lundi au vendredi de 7h30 à 20h, le samedi de 8h à 12h",
     "access": "Tram 1 Médiathèque, accessible PMR",
     "ranges": {"week": [(time(7, 30), time(12, 30)), (time(14), time(20))], "sat": [(time(8), time(12))]},
     "emergency_times": [],
     "practitioners": [("M. Lucas Bernard", "Rééducation post-opératoire & sport"), ("Mme Chloé Roux", "Kiné respiratoire & pédiatrique")]},
    {"slug": "dakar-almadies", "name": "Cabinet Médical des Almadies", "specialty": "generaliste", "country": "SN",
     "timezone": "Africa/Dakar", "address": "Route des Almadies, Dakar", "phone": "+221 33 800 00 01",
     "hours": "du lundi au vendredi de 8h30 à 13h et de 15h à 19h, le samedi de 9h à 13h",
     "access": "Parking devant le cabinet", "voip_provider": "africastalking", "voip_number": "+221338000001",
     "email": "contact.almadies@demo.getcareassist.com",
     "insurance_note": ("Le cabinet accepte le paiement direct et travaille avec plusieurs IPM et assurances privées : "
                        "renseignez-vous auprès du secrétariat avant la consultation (liste à compléter par le cabinet)."),
     "prices_note": "Les tarifs de consultation sont communiqués par le secrétariat (à compléter par le cabinet, en FCFA).",
     "ranges": {"week": [(time(8, 30), time(13)), (time(15), time(19))], "sat": [(time(9), time(13))]},
     "emergency_times": [time(12, 0), time(18, 30)],
     "practitioners": [("Dr Aïssatou Diop", "Médecine générale"), ("Dr Moussa Ndiaye", "Médecine générale & pédiatrie")]},
    {"slug": "douala-bonapriso", "name": "Clinique Dentaire Bonapriso", "specialty": "dentiste", "country": "CM",
     "timezone": "Africa/Douala", "address": "Rue Njo-Njo, Bonapriso, Douala", "phone": "+237 233 00 00 01",
     "hours": "du lundi au vendredi de 8h à 12h30 et de 14h à 18h, le samedi de 8h à 12h",
     "access": "Quartier Bonapriso, parking client", "voip_provider": "vonage", "voip_number": "+237233000001",
     "email": "contact.bonapriso@demo.getcareassist.com",
     "insurance_note": ("Paiement direct au cabinet ; certaines assurances santé privées sont acceptées : "
                        "renseignez-vous auprès du secrétariat (liste à compléter par le cabinet)."),
     "prices_note": "Les tarifs sont communiqués par le secrétariat ; devis gratuit pour les prothèses (en FCFA, à compléter).",
     "ranges": {"week": [(time(8), time(12, 30)), (time(14), time(18))], "sat": [(time(8), time(12))]},
     "emergency_times": [time(12), time(17, 30)],
     "practitioners": [("Dr Brigitte Ngono", "Soins & urgences"), ("Dr Samuel Eto", "Prothèses & implants")]},
]

# Comptes de démo (README) : même mot de passe DEMO_PASSWORD
DEMO_USERS = [
    ("dentiste", "dr.martin@demo.getcareassist.com", "Dr Claire Martin", "owner"),
    ("dentiste", "accueil.parc@demo.getcareassist.com", "Sophie (accueil)", "secretary"),
    ("dentiste", "dr.benali@demo.getcareassist.com", "Dr Karim Benali", "practitioner"),
    ("dakar-almadies", "dr.diop@demo.getcareassist.com", "Dr Aïssatou Diop", "owner"),
    ("douala-bonapriso", "dr.ngono@demo.getcareassist.com", "Dr Brigitte Ngono", "owner"),
]

DEMO_PATIENTS = {
    "dentiste": [("Marie", "Durand", "+33199000101", "marie.durand@example.com", "sms"),
                 ("Lucas", "Bernier", "+33199000102", None, "auto"),
                 ("Nadia", "Haddad", "+33199000103", "nadia.haddad@example.com", "email")],
    "dakar-almadies": [("Fatou", "Sow", "+221770000101", None, "whatsapp"),
                       ("Mamadou", "Fall", "+221770000102", None, "sms"),
                       ("Awa", "Ba", "+221770000103", None, "auto")],
    "douala-bonapriso": [("Jean", "Mbarga", "+237670000101", None, "whatsapp"),
                         ("Grâce", "Tchoumi", "+237670000102", None, "sms"),
                         ("Paul", "Essomba", "+237670000103", None, "auto")],
}

VOIP_FR = {"dentiste": "+33199000001", "psychologue": "+33199000002", "ophtalmologue": "+33199000003",
           "generaliste": "+33199000004", "kinesitherapeute": "+33199000005"}



def _ascii(s: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _ranges(p: dict, d: date):
    wd = d.weekday()
    if wd < 5:
        return p["ranges"]["week"]
    if wd == 5:
        return p["ranges"]["sat"]
    return []


def seed(days: int = 14) -> int:
    """Idempotent : ajoute cabinets, praticiens et créneaux manquants. Renvoie le nb de créneaux créés."""
    db.init_db()
    from .countries import get_country
    from .phone import to_e164
    created = 0
    with db.get_conn() as conn:
        for p in PRACTICES:
            country = p.get("country", "FR")
            prof = get_country(country)
            tz = p.get("timezone", prof["timezone"])
            today = db.now(tz).date()
            row = conn.execute("SELECT id FROM practices WHERE slug=?", (p["slug"],)).fetchone()
            if row:
                practice_id = row[0]
                # base créée par une version antérieure : complète les nouveaux champs
                conn.execute("UPDATE practices SET voip_number=COALESCE(voip_number, ?), is_demo=1, "
                             "email=COALESCE(email, ?) WHERE id=?",
                             (p.get("voip_number") or VOIP_FR.get(p["slug"]), f"contact.{p['slug']}@demo.getcareassist.com", practice_id))
            else:
                practice_id = conn.execute(
                    "INSERT INTO practices(slug, name, specialty, address, phone, hours, access, country, timezone, currency, "
                    "email, phone_e164, voip_provider, voip_number, insurance_note, prices_note, is_demo, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
                    (p["slug"], p["name"], p["specialty"], p["address"], p["phone"], p["hours"], p["access"], country, tz,
                     prof["currency"], p.get("email") or f"contact.{p['slug']}@demo.getcareassist.com",
                     to_e164(p["phone"], country, strict=False), p.get("voip_provider", "twilio"),
                     p.get("voip_number") or VOIP_FR.get(p["slug"]), p.get("insurance_note"), p.get("prices_note"), db.now_iso()),
                ).lastrowid
                conn.executemany(
                    "INSERT INTO practitioners(practice_id, name, specialty, email) VALUES (?,?,?,?)",
                    [(practice_id, n, s, f"{_ascii(n.split()[-1])}.{p['slug']}@demo.getcareassist.com")
                     for n, s in p["practitioners"]],
                )
            if not conn.execute("SELECT 1 FROM opening_hours WHERE practice_id=?", (practice_id,)).fetchone():
                hours = []
                for wd in range(6):
                    for a, b in (p["ranges"]["week"] if wd < 5 else p["ranges"]["sat"]):
                        hours.append((practice_id, wd, a.strftime("%H:%M"), b.strftime("%H:%M")))
                conn.executemany("INSERT INTO opening_hours(practice_id, weekday, open_time, close_time) VALUES (?,?,?,?)", hours)
            prac_ids = [r[0] for r in conn.execute(
                "SELECT id FROM practitioners WHERE practice_id=? ORDER BY id", (practice_id,)).fetchall()]
            step = SPECIALTIES[p["specialty"]]["slot_minutes"]
            em_times = set(p["emergency_times"])
            for offset in range(days):
                d = today + timedelta(days=offset)
                for start_t, end_t in _ranges(p, d):
                    cur, end = datetime.combine(d, start_t), datetime.combine(d, end_t)
                    while cur + timedelta(minutes=step) <= end:
                        for pid in prac_ids:
                            is_em = int(pid == prac_ids[0] and cur.time() in em_times)
                            # ~1/3 des créneaux standards déjà pris (motif déterministe) pour le réalisme
                            pre = 0 if is_em else int((cur.day * 7 + cur.hour * 3 + cur.minute + pid) % 3 == 0)
                            res = conn.execute(
                                "INSERT OR IGNORE INTO slots(practitioner_id, start, duration_min, is_emergency, booked) "
                                "VALUES (?,?,?,?,?)",
                                (pid, cur.strftime("%Y-%m-%dT%H:%M"), step, is_em, pre),
                            )
                            created += res.rowcount
                        cur += timedelta(minutes=step)
    _seed_accounts()
    return created


def _seed_accounts() -> None:
    """Comptes, patients et rendez-vous de démo (idempotent : seulement si le cabinet n'a encore aucun patient)."""
    from . import auth, booking
    with db.get_conn() as conn:
        for slug, email, name, role in DEMO_USERS:
            pid = conn.execute("SELECT id FROM practices WHERE slug=?", (slug,)).fetchone()[0]
            if not conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
                prac = conn.execute("SELECT id FROM practitioners WHERE practice_id=? AND name=?", (pid, name)).fetchone()
                auth.create_user(pid, email, DEMO_PASSWORD, name, role, prac[0] if prac else None, conn=conn)
    for slug, pats in DEMO_PATIENTS.items():
        p = db.get_practice(slug)
        with db.get_conn() as conn:
            if conn.execute("SELECT 1 FROM patients WHERE practice_id=?", (p["id"],)).fetchone():
                continue
            ids = []
            for fn, ln, ph, em, ch in pats:
                ids.append(conn.execute(
                    "INSERT INTO patients(practice_id, first_name, last_name, phone_e164, email, preferred_channel, notify_consent, "
                    "source, notes, created_at, updated_at) VALUES (?,?,?,?,?,?,1,'import','Patient fictif (démo)',?,?)",
                    (p["id"], fn, ln, ph, em, ch, db.now_iso(), db.now_iso())).lastrowid)
        # 1 RDV demain + 1 RDV dans 3 jours, réservés par le cabinet -> confirmation + rappels planifiés
        for i, (pat_id, pat) in enumerate(zip(ids, pats)):
            if i > 1:
                break
            day = db.now(p["timezone"]).date() + timedelta(days=1 + 2 * i)
            slots = booking.find_slots(day=day, practice_id=p["id"], limit=3) or booking.find_slots(practice_id=p["id"], limit=1)
            if slots:
                try:
                    booking.book(slots[-1]["id"], f"{pat[0]} {pat[1]}", pat[2], "Consultation", practice_id=p["id"],
                                 patient_id=pat_id, source="cabinet")
                except booking.BookingError:
                    pass

    # Cabinets de démo : Premium, fiches déjà publiées, ville renseignée
    from . import directory, plans
    with db.get_conn() as conn:
        for row in conn.execute("SELECT id, address, city, is_demo FROM practices").fetchall():
            city = row["city"] or directory.infer_city(row["address"])
            if row["is_demo"]:
                conn.execute(
                    "UPDATE practices SET plan=?, subscription_status=?, trial_ends_at=NULL, "
                    "listing_status=?, published_at=COALESCE(published_at, ?), directory_visible=1, city=? WHERE id=?",
                    (plans.PLAN_PREMIUM, plans.STATUS_ACTIVE, "published", db.now_iso(), city, row["id"]),
                )
            elif city and not row["city"]:
                conn.execute("UPDATE practices SET city=? WHERE id=?", (city, row["id"]))


if __name__ == "__main__":

    print(f"Seed OK — {seed()} créneaux ajoutés")
