"""Configuration par spécialité : types de RDV, FAQ, notes assurance, règles d'urgence,
surcouche du prompt système, exemples de démo et presets ROI.

Les motifs (regex) s'appliquent à un texte normalisé : minuscules, sans accents,
apostrophes droites (voir emergency.normalize). Les montants/remboursements sont
volontairement génériques : chaque cabinet doit les valider/personnaliser.
"""
from __future__ import annotations

# ----------------------------------------------------------------------------
# Règles d'urgence communes à TOUTES les spécialités (signes de gravité vitale)
# action: samu -> appeler le 15/112 immédiatement, aucun RDV proposé
# ----------------------------------------------------------------------------
COMMON_EMERGENCY_RULES = [
    {
        "id": "suicide", "level": "vital", "action": "samu_psy",
        "patterns": [r"suicid", r"me tuer", r"en finir", r"mettre fin a (mes|ma) (jours|vie)",
                     r"(plus|pas) envie de vivre", r"envie de mourir", r"me faire du mal", r"scarifi",
                     r"\b(veux|voudrais|vais|aimerais|prefererais) (mourir(?! de rire)|disparaitre)", r"me pendre", r"me jeter (sous|du|d'un|par)",
                     r"(avale|avaler|pris|prendre) .{0,20}(boite|plaquette|tous mes|toutes mes).{0,15}(medicaments|cachets|comprimes|pilules)",
                     r"kill myself", r"want to die", r"end my life"],
    },
    {
        "id": "respiration", "level": "vital", "action": "samu",
        "patterns": [r"(du mal|difficulte|n'?arrive (pas|plus)|peine|peux (pas|plus)|peut (pas|plus)) a respirer",
                     r"etouff", r"souffle coupe", r"respire (mal|plus)"],
    },
    {
        "id": "conscience", "level": "vital", "action": "samu",
        "patterns": [r"perte de connaissance", r"evanoui", r"inconscient", r"ne repond plus", r"convuls"],
    },
    {
        "id": "douleur_thoracique", "level": "vital", "action": "samu",
        "patterns": [r"douleur (dans la |a la |en |de )?poitrine", r"douleur thoracique", r"mal (a|dans) la poitrine",
                     r"(serrement|oppression|poids) (dans |a |sur )?la poitrine", r"oppression thoracique"],
    },
    {
        "id": "avc", "level": "vital", "action": "samu",
        "patterns": [r"bouche (de travers|deformee|tordue)", r"visage (paralyse|deforme|de travers)",
                     r"paralys", r"(n'?arrive|ne peux|ne peut) plus (bouger|parler)",
                     r"bras (engourdi|faible|qui ne repond)", r"trouble(s)? de la parole", r"\bavc\b"],
    },
    {
        "id": "hemorragie", "level": "vital", "action": "samu",
        "patterns": [r"hemorragie", r"saigne (enormement|beaucoup|abondamment)",
                     r"saignement (qui ne s'?arrete pas|abondant|important|massif)", r"(ca|le sang) ne s'?arrete pas"],
    },
    {
        "id": "allergie_grave", "level": "vital", "action": "samu",
        "patterns": [r"gorge (gonflee|qui gonfle|serree)", r"levres? (gonflee|qui gonfle)", r"choc anaphylactique",
                     r"langue (gonflee|qui gonfle)"],
    },
]

SPECIALTIES: dict[str, dict] = {
    # ------------------------------------------------------------------ DENTISTE
    "dentiste": {
        "label": "Chirurgien-dentiste",
        "label_en": "Dentist",
        "icon": "tooth",
        "slot_minutes": 30,
        "has_emergency_slots": True,
        "appointment_types": [
            {"key": "urgence", "label": "Urgence dentaire", "duration": 30, "keywords": [r"urgence", r"douleur", r"mal"]},
            {"key": "detartrage", "label": "Détartrage", "duration": 30, "keywords": [r"detartr", r"tartre", r"nettoyage"]},
            {"key": "soin", "label": "Soin (carie, plombage)", "duration": 30, "keywords": [r"carie", r"plombage", r"soin", r"obturation"]},
            {"key": "implant", "label": "Consultation implant / prothèse", "duration": 30, "keywords": [r"implant", r"prothese", r"couronne", r"bridge", r"dentier"]},
            {"key": "blanchiment", "label": "Consultation blanchiment", "duration": 30, "keywords": [r"blanchi", r"esthetique"]},
            {"key": "orthodontie", "label": "Consultation orthodontie", "duration": 30, "keywords": [r"orthodont", r"appareil", r"gouttiere", r"bagues"]},
            {"key": "controle", "label": "Consultation / contrôle", "duration": 30, "keywords": [r"controle", r"bilan", r"visite", r"consultation", r"check"]},
        ],
        "insurance": ("Nous acceptons la carte Vitale. Le tiers payant est généralement pratiqué sur la part Assurance Maladie "
                      "pour les soins courants ; la part mutuelle dépend de votre contrat. Les bénéficiaires de la "
                      "Complémentaire santé solidaire (C2S, ex-CMU-C) sont bien sûr reçus. Les prothèses relevant du "
                      "« 100 % Santé » peuvent être sans reste à charge ; pour les implants et prothèses hors panier, "
                      "un devis vous est remis avant tout traitement."),
        "prices": ("Les soins courants sont facturés selon les tarifs conventionnels. Les prothèses, implants, "
                   "l'orthodontie adulte et le blanchiment font l'objet d'un devis personnalisé remis par le praticien. "
                   "Je ne peux pas vous donner de prix exact sans examen."),
        "faq": [
            {"patterns": [r"enfant", r"fils", r"fille", r"bebe"], "answer": "Oui, le cabinet reçoit les enfants. L'examen bucco-dentaire « M'T dents » est pris en charge par l'Assurance Maladie aux âges concernés."},
            {"patterns": [r"anesthesi", r"peur", r"phobie"], "answer": "C'est fréquent, rassurez-vous : signalez-le au praticien, il adaptera la séance (explications, pauses, anesthésie locale)."},
        ],
        "emergency_rules": [
            {"id": "cellulite", "level": "vital", "action": "samu",
             "patterns": [r"gonfl\w* .*(cou|gorge|sous l'?oeil|jusqu'?a l'?oeil)", r"(du mal|n'?arrive (pas|plus)|peux (pas|plus)) a (avaler|ouvrir la bouche)"]},
            {"id": "traumatisme", "level": "urgent", "action": "priority_slot",
             "patterns": [r"dent (cassee|casse|fendue|tombee|expulsee|arrachee|deplacee|cassée)", r"casse (une|ma|la) dent",
                          r"choc (sur|a|dans) (la|une|ma|les) (dent|bouche)", r"tombe sur (la|les) (bouche|dents)", r"chute"]},
            {"id": "gonflement", "level": "urgent", "action": "priority_slot",
             "patterns": [r"gonfl", r"enfl", r"abces"]},
            {"id": "saignement", "level": "urgent", "action": "priority_slot", "patterns": [r"saign"]},
            {"id": "fievre", "level": "urgent", "action": "priority_slot", "patterns": [r"fievre"]},
            {"id": "douleur", "level": "urgent", "action": "priority_slot",
             "patterns": [r"rage de dents?", r"mal (aux|a une|a la|a ma) dents?", r"douleur (dentaire|intense|insupportable|atroce|forte|terrible)",
                          r"tres mal", r"insupportable", r"pas dormi"]},
        ],
        "advice": {
            "traumatisme": "Si une dent définitive est tombée : tenez-la par la couronne (pas par la racine), ne la frottez pas, conservez-la dans du lait ou du sérum physiologique et venez au plus vite (idéalement dans l'heure).",
            "gonflement": "En attendant : appliquez du froid sur la joue (jamais de chaleur), ne percez pas le gonflement. Si le gonflement s'étend au cou ou à l'œil, ou si vous avez du mal à avaler ou à respirer, appelez [[SAMU_SHORT]].",
            "saignement": "Mordez sur une compresse propre pendant 20 minutes sans la retirer. Si le saignement ne s'arrête pas, appelez [[SAMU_SHORT]].",
            "fievre": "Une fièvre associée à une douleur dentaire peut signaler une infection : surveillez-la. En cas de fièvre élevée avec gonflement, appelez [[SAMU_SHORT]].",
            "douleur": "En attendant, vous pouvez prendre un antalgique habituel en respectant la notice ; évitez l'aspirine en cas de saignement.",
        },
        "prompt_overlay": ("Spécialité : cabinet dentaire. Motifs fréquents : contrôle, détartrage, caries, urgences (douleur, "
                           "gonflement, dent cassée), implants/prothèses (sur devis), orthodontie. Des créneaux d'urgence sont "
                           "réservés chaque jour. Dent expulsée : conserver dans du lait, venir dans l'heure. Gonflement qui "
                           "s'étend au cou/à l'œil ou gêne pour avaler/respirer : [[SAMU_NUM]] immédiatement."),
        "demo_examples": ["Bonjour, je voudrais un détartrage demain matin", "Vous faites le tiers payant avec la mutuelle ?",
                          "J'ai la joue gonflée et très mal depuis hier soir"],
        "roi_preset": {"missed_calls": 5, "new_share": 20, "conversion": 50, "value": 450},
    },
    # ------------------------------------------------------------------ PSY
    "psychologue": {
        "label": "Psychologue / psychothérapeute",
        "label_en": "Psychologist / psychotherapist",
        "icon": "brain",
        "slot_minutes": 60,
        "has_emergency_slots": False,
        "appointment_types": [
            {"key": "premier", "label": "Premier entretien", "duration": 60, "keywords": [r"premier", r"premiere", r"debut", r"jamais (venu|consulte)", r"nouveau"]},
            {"key": "couple", "label": "Thérapie de couple", "duration": 60, "keywords": [r"couple", r"conjoint", r"mari", r"femme"]},
            {"key": "enfant", "label": "Séance enfant / adolescent", "duration": 50, "keywords": [r"enfant", r"ado", r"fils", r"fille"]},
            {"key": "visio", "label": "Téléconsultation (visio)", "duration": 50, "keywords": [r"visio", r"distance", r"teleconsult", r"en ligne"]},
            {"key": "seance", "label": "Séance individuelle", "duration": 50, "keywords": [r"seance", r"suivi", r"consultation", r"rendez"]},
        ],
        "insurance": ("Les séances de psychologue ne sont pas remboursées par défaut, mais le dispositif « Mon soutien psy » "
                      "de l'Assurance Maladie permet une prise en charge d'un nombre limité de séances par an si le psychologue "
                      "y est conventionné (à vérifier avec le cabinet). De nombreuses mutuelles remboursent aussi quelques "
                      "séances par an : renseignez-vous auprès de la vôtre. Une facture vous est remise à chaque séance."),
        "prices": ("Le tarif des séances est fixé par le praticien et vous sera précisé lors de la prise de rendez-vous ; "
                   "le premier entretien peut être un peu plus long. Je ne peux pas m'engager sur un montant à sa place."),
        "faq": [
            {"patterns": [r"confidenti", r"secret", r"anonym"], "answer": "Tout ce qui est dit en séance est couvert par le secret professionnel. De mon côté, je ne collecte que votre nom et un numéro pour le rendez-vous."},
            {"patterns": [r"visio", r"distance", r"teleconsult"], "answer": "Oui, des séances en visioconférence sont possibles ; le lien vous est envoyé avant la séance."},
        ],
        "emergency_rules": [
            {"id": "danger", "level": "vital", "action": "samu_danger",
             "patterns": [r"(il|elle|on) (me|m') (frappe|bat|menace)", r"je suis en danger", r"violence(s)? (conjugale|a la maison)"]},
            {"id": "crise", "level": "urgent", "action": "soonest_slot",
             "patterns": [r"crise d'?angoisse", r"crise de panique", r"attaque de panique", r"angoisse (forte|terrible|insupportable)",
                          r"je craque", r"(ne|n') ?vais (pas|vraiment pas) bien", r"detresse", r"au bout du rouleau", r"je n'?en peux plus"]},
        ],
        "advice": {
            "crise": "Si l'angoisse devient trop forte ou si des idées noires apparaissent, appelez dès maintenant [[SUICIDE]], et [[SAMU_SHORT]] en cas de danger immédiat.",
        },
        "prompt_overlay": ("Spécialité : cabinet de psychologue / psychothérapeute. Ton particulièrement doux, empathique, sans "
                           "jugement. Tu n'es PAS thérapeute : ne fais jamais d'analyse, de conseil psychologique ni de "
                           "diagnostic ; ne demande pas le motif détaillé de consultation (juste le type de séance). "
                           "Toute mention d'idées suicidaires, d'auto-agression ou de danger : réponds avec empathie et "
                           "donne IMMÉDIATEMENT [[SUICIDE]] et [[SAMU_OR_112]] en cas de "
                           "danger immédiat ; encourage à ne pas rester seul ; ne propose pas un simple rendez-vous à la place."),
        "demo_examples": ["Bonjour, je voudrais prendre un premier rendez-vous", "Est-ce que les séances sont remboursées ?",
                          "Je suis en pleine crise d'angoisse, je ne vais pas bien"],
        "roi_preset": {"missed_calls": 2, "new_share": 40, "conversion": 50, "value": 600},
    },
    # ------------------------------------------------------------------ OPHTALMO
    "ophtalmologue": {
        "label": "Ophtalmologue",
        "label_en": "Ophthalmologist",
        "icon": "eye",
        "slot_minutes": 20,
        "has_emergency_slots": True,
        "appointment_types": [
            {"key": "urgence", "label": "Consultation urgente", "duration": 20, "keywords": [r"urgence", r"urgent"]},
            {"key": "fond_oeil", "label": "Fond d'œil / dilatation", "duration": 30, "keywords": [r"fond d'?oeil", r"dilat", r"diabet", r"retine"]},
            {"key": "glaucome", "label": "Suivi glaucome", "duration": 20, "keywords": [r"glaucome", r"tension (de l'|oculaire)"]},
            {"key": "preop", "label": "Bilan cataracte / chirurgie réfractive", "duration": 30, "keywords": [r"cataracte", r"laser", r"lasik", r"chirurgie", r"operation"]},
            {"key": "enfant", "label": "Consultation enfant", "duration": 20, "keywords": [r"enfant", r"fils", r"fille", r"bebe", r"strabisme"]},
            {"key": "refraction", "label": "Consultation lunettes / lentilles", "duration": 20, "keywords": [r"lunette", r"lentille", r"vue", r"ordonnance", r"controle", r"consultation"]},
        ],
        "insurance": ("Carte Vitale acceptée. L'ophtalmologue est accessible sans passer par le médecin traitant pour les "
                      "lunettes, lentilles et le suivi du glaucome. Selon le secteur du praticien, des dépassements "
                      "d'honoraires peuvent s'appliquer et être pris en charge par votre mutuelle selon votre contrat. "
                      "Les bénéficiaires de la C2S sont reçus sans dépassement."),
        "prices": ("La consultation est facturée selon le secteur conventionnel du praticien ; certains examens "
                   "complémentaires (champ visuel, OCT…) s'ajoutent si nécessaire. Le tarif exact vous sera confirmé par le cabinet."),
        "faq": [
            {"patterns": [r"dilat", r"conduire", r"voiture"], "answer": "Si un fond d'œil avec dilatation est prévu, votre vision sera floue quelques heures : ne conduisez pas après la consultation et venez accompagné si possible."},
            {"patterns": [r"renouvel", r"ordonnance"], "answer": "Pour un renouvellement de lunettes, apportez vos lunettes actuelles et votre ancienne ordonnance. Un opticien peut aussi, sous conditions, adapter une ordonnance encore valide."},
        ],
        "emergency_rules": [
            {"id": "brulure_chimique", "level": "vital", "action": "samu",
             "patterns": [r"(produit|liquide) (chimique|menager|ménager)", r"javel", r"acide", r"soude", r"chaux", r"ciment",
                          r"projection .*(oeil|yeux)", r"(oeil|yeux) .*brul", r"brul.*(oeil|yeux)"]},
            {"id": "perte_vision", "level": "vital", "action": "samu",
             "patterns": [r"(perte|baisse) (brutale|soudaine|subite|brusque) (de la |d'?)?(vue|vision)",
                          r"ne vois (plus|soudain) (rien|d'?un oeil)", r"vision (noire|devenue noire)", r"voile noir", r"rideau"]},
            {"id": "decollement", "level": "urgent", "action": "priority_slot",
             "patterns": [r"eclairs?", r"flash", r"corps flottants?", r"mouches? volantes?", r"(points|taches) noir"]},
            {"id": "traumatisme_oeil", "level": "urgent", "action": "priority_slot",
             "patterns": [r"(coup|choc|balle|ballon) .*(oeil|yeux)", r"corps etranger", r"(poussiere|eclat|copeau) .*(oeil|yeux)"]},
            {"id": "oeil_rouge_douloureux", "level": "urgent", "action": "priority_slot",
             "patterns": [r"oeil (tres )?(rouge et douloureux|douloureux)", r"douleur (a|de|dans) l'?oeil", r"mal (a l'?|aux |a un )(oeil|yeux)",
                          r"vision (trouble|floue) (soudaine|brutale|d'un coup)"]},
        ],
        "advice": {
            "decollement": "L'apparition d'éclairs lumineux ou de taches noires doit être examinée le jour même (risque de déchirure de la rétine). Si un voile ou un rideau apparaît dans votre champ de vision, appelez [[SAMU_SHORT]] ou rendez-vous aux urgences ophtalmologiques.",
            "traumatisme_oeil": "Ne frottez pas l'œil et ne tentez pas de retirer un objet planté. Si la douleur est intense ou la vision baisse, rendez-vous aux urgences ophtalmologiques.",
            "oeil_rouge_douloureux": "Un œil rouge ET douloureux, surtout avec baisse de vision, doit être vu rapidement. Retirez vos lentilles si vous en portez.",
        },
        "prompt_overlay": ("Spécialité : cabinet d'ophtalmologie. Motifs : lunettes/lentilles, fond d'œil, glaucome, cataracte, "
                           "enfants, urgences. Projection chimique dans l'œil : rincer immédiatement à l'eau claire 15 minutes "
                           "et appeler [[SAMU_SHORT]]. Perte brutale de vision ou voile/rideau : [[SAMU_NUM]] / urgences ophtalmologiques. "
                           "Éclairs ou taches noires récentes : créneau urgent le jour même. Rappeler de ne pas conduire après dilatation."),
        "demo_examples": ["Je voudrais un rendez-vous pour renouveler mes lunettes", "Je vois des éclairs et des taches noires depuis ce matin",
                          "J'ai reçu de la javel dans l'œil"],
        "roi_preset": {"missed_calls": 10, "new_share": 30, "conversion": 60, "value": 120},
    },
    # ------------------------------------------------------------------ GÉNÉRALISTE
    "generaliste": {
        "label": "Médecin généraliste",
        "label_en": "General practitioner",
        "icon": "stethoscope",
        "slot_minutes": 20,
        "has_emergency_slots": True,
        "appointment_types": [
            {"key": "urgence", "label": "Consultation du jour (soins non programmés)", "duration": 20, "keywords": [r"urgence", r"urgent", r"aujourd'?hui"]},
            {"key": "certificat", "label": "Certificat médical", "duration": 20, "keywords": [r"certificat", r"sport", r"licence"]},
            {"key": "vaccin", "label": "Vaccination", "duration": 20, "keywords": [r"vaccin", r"rappel"]},
            {"key": "suivi", "label": "Suivi / renouvellement", "duration": 20, "keywords": [r"suivi", r"renouvel", r"ordonnance", r"chronique", r"tension", r"diabete"]},
            {"key": "visio", "label": "Téléconsultation", "duration": 20, "keywords": [r"visio", r"teleconsult", r"distance"]},
            {"key": "consultation", "label": "Consultation", "duration": 20, "keywords": [r"consultation", r"rendez", r"voir le (docteur|medecin)"]},
        ],
        "insurance": ("Carte Vitale acceptée. Déclarer ce médecin comme médecin traitant vous garantit le meilleur "
                      "remboursement dans le parcours de soins. Le tiers payant s'applique notamment pour les bénéficiaires "
                      "de la C2S, de l'AME, les patients en ALD et la maternité ; pour les autres, la part mutuelle dépend de votre contrat."),
        "prices": "Les consultations sont facturées au tarif conventionnel en vigueur (secteur du praticien précisé par le cabinet).",
        "faq": [
            {"patterns": [r"domicile", r"se deplacer", r"visite a la maison"], "answer": "Les visites à domicile sont réservées aux patients qui ne peuvent pas se déplacer ; je transmets votre demande au médecin qui vous rappellera."},
            {"patterns": [r"garde", r"week-?end", r"nuit", r"dimanche"], "answer": "[[AFTER_HOURS]]"},
        ],
        "emergency_rules": [
            {"id": "fievre_nourrisson", "level": "vital", "action": "samu",
             "patterns": [r"(bebe|nourrisson|nouveau-ne).*(fievre|39|40|ne boit plus|mou)", r"fievre.*(bebe|nourrisson|nouveau-ne)"]},
            {"id": "purpura_meninges", "level": "vital", "action": "samu",
             "patterns": [r"purpura", r"taches? (violett|rouge).*fievre", r"nuque (raide|bloquee)"]},
            {"id": "soins_du_jour", "level": "urgent", "action": "priority_slot",
             "patterns": [r"fievre", r"vomi", r"diarrhee", r"mal au ventre", r"douleur (au ventre|abdominale)", r"brulures? (en urinant|urinaire)",
                          r"cystite", r"angine", r"otite", r"infection"]},
        ],
        "advice": {
            "soins_du_jour": "Hydratez-vous bien en attendant. Si l'état s'aggrave rapidement (difficultés à respirer, confusion, taches sur la peau qui ne s'effacent pas), appelez [[SAMU_SHORT]].",
        },
        "prompt_overlay": ("Spécialité : cabinet de médecine générale. Motifs : consultation, soins du jour, renouvellement, "
                           "certificat, vaccination, suivi chronique, téléconsultation. Douleur thoracique, signes d'AVC "
                           "(bouche de travers, bras faible, trouble de la parole), détresse respiratoire, fièvre chez un "
                           "nourrisson, taches violacées avec fièvre : [[SAMU_NUM]] immédiatement. Hors horaires : [[AFTER_HOURS]]"),
        "demo_examples": ["Je voudrais une consultation aujourd'hui, j'ai de la fièvre", "Vous faites le tiers payant ?",
                          "J'ai une douleur dans la poitrine qui serre"],
        "roi_preset": {"missed_calls": 20, "new_share": 15, "conversion": 70, "value": 90},
    },
    # ------------------------------------------------------------------ KINÉ
    "kinesitherapeute": {
        "label": "Masseur-kinésithérapeute",
        "label_en": "Physiotherapist",
        "icon": "activity",
        "slot_minutes": 30,
        "has_emergency_slots": False,
        "appointment_types": [
            {"key": "postop", "label": "Rééducation post-opératoire", "duration": 30, "keywords": [r"opera", r"opere", r"chirurgie", r"prothese", r"ligament", r"ligamentoplastie", r"menisque"]},
            {"key": "respiratoire", "label": "Kiné respiratoire", "duration": 30, "keywords": [r"respiratoire", r"bronchiolite", r"encombre"]},
            {"key": "bilan", "label": "Bilan initial", "duration": 30, "keywords": [r"bilan", r"premier", r"premiere", r"nouveau"]},
            {"key": "seance", "label": "Séance de rééducation", "duration": 30, "keywords": [r"seance", r"reeduc", r"dos", r"entorse", r"tendin", r"rendez"]},
        ],
        "insurance": ("Les séances sont prises en charge par l'Assurance Maladie sur prescription médicale (ordonnance), "
                      "le complément par votre mutuelle selon votre contrat. Le tiers payant est souvent pratiqué : "
                      "apportez carte Vitale, attestation de mutuelle et ordonnance. L'accès direct sans prescription "
                      "n'existe que dans certains cadres limités : demandez au cabinet."),
        "prices": "Les séances sont facturées au tarif conventionnel ; certains actes hors nomenclature peuvent être proposés, avec information préalable du tarif.",
        "faq": [
            {"patterns": [r"apporter", r"tenue", r"quoi prendre"], "answer": "Apportez votre ordonnance, vos comptes rendus et examens d'imagerie, votre carte Vitale, une serviette et une tenue confortable."},
            {"patterns": [r"domicile"], "answer": "Les séances à domicile sont possibles si elles sont prescrites (mention « à domicile » sur l'ordonnance) et selon les disponibilités."},
        ],
        "emergency_rules": [
            {"id": "embolie", "level": "vital", "action": "samu",
             "patterns": [r"essouffl\w* (brutal|soudain|d'un coup)", r"(brutalement|soudain|d'un coup) essouffl", r"crache du sang"]},
            {"id": "phlebite", "level": "urgent", "action": "redirect",
             "patterns": [r"mollet\b.{0,25}(gonfl|chaud|rouge|dur|douloureux)", r"jambe\b.{0,25}(gonfl|chaud|rouge)", r"phlebite", r"thrombose"]},
            {"id": "cicatrice_infection", "level": "urgent", "action": "redirect",
             "patterns": [r"cicatrice .*(rouge|chaude|coule|pus|ecoulement|ouverte|gonfl)", r"(pus|ecoulement) .*cicatrice",
                          r"fievre .*(operation|opere|intervention|chirurgie)", r"(operation|opere|intervention|chirurgie) .*fievre"]},
            {"id": "neuro", "level": "urgent", "action": "redirect",
             "patterns": [r"perte de (force|sensibilite)", r"ne sens plus (ma|mes|mon)", r"fourmillements? .*(jambe|bras|pied)",
                          r"(incontinence|perte d'urine) .*(dos|sciatique)", r"anesthesie en selle"]},
        ],
        "advice": {
            "phlebite": "Un mollet gonflé, chaud ou douloureux après une opération peut évoquer une phlébite : contactez aujourd'hui votre chirurgien ou votre médecin (ou [[SAMU_SHORT]] si vous êtes essoufflé ou avez mal à la poitrine). Ne faites pas d'exercices sur cette jambe en attendant.",
            "cicatrice_infection": "Une cicatrice rouge, chaude, qui coule, ou de la fièvre après l'opération doit être vue aujourd'hui par votre chirurgien ou votre médecin.",
            "neuro": "Une perte de force, de sensibilité ou des troubles urinaires associés au dos nécessitent un avis médical urgent aujourd'hui (médecin, chirurgien ou [[SAMU_NUM]]).",
        },
        "prompt_overlay": ("Spécialité : cabinet de kinésithérapie. Motifs : bilan, rééducation (dos, entorse, tendinite), "
                           "post-opératoire, respiratoire. Séances sur ordonnance. Signaux d'alerte post-opératoires "
                           "(mollet gonflé/chaud, cicatrice rouge qui coule, fièvre, perte de force) : orienter vers le "
                           "chirurgien/médecin le jour même, pas vers une séance de kiné ; essoufflement brutal ou douleur thoracique : [[SAMU_NUM]]."),
        "demo_examples": ["Je dois commencer la rééducation après mon opération du genou", "Faut-il une ordonnance pour venir ?",
                          "Mon mollet est gonflé et chaud depuis l'opération"],
        "roi_preset": {"missed_calls": 6, "new_share": 30, "conversion": 60, "value": 300},
    },
}

ALIASES = {
    "dentist": "dentiste", "dental": "dentiste", "psy": "psychologue", "psychotherapeute": "psychologue",
    "psychologist": "psychologue", "ophtalmo": "ophtalmologue", "ophthalmologist": "ophtalmologue",
    "medecin": "generaliste", "gp": "generaliste", "medecin-generaliste": "generaliste",
    "kine": "kinesitherapeute", "physio": "kinesitherapeute",
}


def get_specialty(key: str | None) -> dict:
    key = (key or "dentiste").lower()
    key = ALIASES.get(key, key)
    spec = SPECIALTIES.get(key) or SPECIALTIES["dentiste"]
    return {"key": key if key in SPECIALTIES else "dentiste", **spec}


def public_specialties() -> list[dict]:
    """Vue publique (landing page) : sans regex."""
    out = []
    for key, s in SPECIALTIES.items():
        out.append({
            "key": key, "label": s["label"], "label_en": s["label_en"], "icon": s["icon"],
            "appointment_types": [{"key": t["key"], "label": t["label"], "duration": t["duration"]} for t in s["appointment_types"]],
            "demo_examples": s["demo_examples"], "roi_preset": s["roi_preset"],
        })
    return out
