import hashlib


ALPHABETS = {
    "DNA": set("ACGTRYSWKMBDHVN"),
    "RNA": set("ACGURYSWKMBDHVN"),
    "PROTEIN": set("ACDEFGHIKLMNPQRSTVWYBXZJUO*"),
}

DNA_COMPLEMENT = str.maketrans("ACGTRYSWKMBDHVN", "TGCAYRSWMKVHDBN")
RNA_COMPLEMENT = str.maketrans("ACGURYSWKMBDHVN", "UGCAYRSWMKVHDBN")

CODON_TABLE = {
    "TTT":"F","TTC":"F","TTA":"L","TTG":"L","TCT":"S","TCC":"S","TCA":"S","TCG":"S",
    "TAT":"Y","TAC":"Y","TAA":"*","TAG":"*","TGT":"C","TGC":"C","TGA":"*","TGG":"W",
    "CTT":"L","CTC":"L","CTA":"L","CTG":"L","CCT":"P","CCC":"P","CCA":"P","CCG":"P",
    "CAT":"H","CAC":"H","CAA":"Q","CAG":"Q","CGT":"R","CGC":"R","CGA":"R","CGG":"R",
    "ATT":"I","ATC":"I","ATA":"I","ATG":"M","ACT":"T","ACC":"T","ACA":"T","ACG":"T",
    "AAT":"N","AAC":"N","AAA":"K","AAG":"K","AGT":"S","AGC":"S","AGA":"R","AGG":"R",
    "GTT":"V","GTC":"V","GTA":"V","GTG":"V","GCT":"A","GCC":"A","GCA":"A","GCG":"A",
    "GAT":"D","GAC":"D","GAA":"E","GAG":"E","GGT":"G","GGC":"G","GGA":"G","GGG":"G",
}

AMINO_ACID_WEIGHTS = {
    "A":89.09,"R":174.20,"N":132.12,"D":133.10,"C":121.15,"E":147.13,"Q":146.15,
    "G":75.07,"H":155.16,"I":131.17,"L":131.17,"K":146.19,"M":149.21,"F":165.19,
    "P":115.13,"S":105.09,"T":119.12,"W":204.23,"Y":181.19,"V":117.15,
}

RESTRICTION_ENZYMES = {
    "EcoRI": {"site": "GAATTC", "cut": 1},
    "BamHI": {"site": "GGATCC", "cut": 1},
    "HindIII": {"site": "AAGCTT", "cut": 1},
    "PstI": {"site": "CTGCAG", "cut": 5},
    "XhoI": {"site": "CTCGAG", "cut": 1},
    "NotI": {"site": "GCGGCCGC", "cut": 2},
    "NheI": {"site": "GCTAGC", "cut": 1},
    "SpeI": {"site": "ACTAGT", "cut": 1},
}


def clean_sequence(value):
    return "".join(str(value or "").split()).upper()


def validate_alphabet(sequence, sequence_type):
    cleaned = clean_sequence(sequence)
    if not cleaned:
        raise ValueError("Sequence cannot be empty.")
    alphabet = ALPHABETS.get(sequence_type)
    if not alphabet:
        raise ValueError("Choose DNA, RNA, or PROTEIN.")
    invalid = sorted(set(cleaned) - alphabet)
    if invalid:
        raise ValueError(
            f"Invalid {sequence_type} symbol(s): {', '.join(invalid)}."
        )
    return cleaned


def sequence_checksum(sequence, sequence_type):
    cleaned = validate_alphabet(sequence, sequence_type)
    return hashlib.sha256(f"{sequence_type}:{cleaned}".encode("ascii")).hexdigest()


def reverse_complement(sequence, sequence_type="DNA"):
    cleaned = validate_alphabet(sequence, sequence_type)
    if sequence_type == "PROTEIN":
        raise ValueError("Protein sequences do not have a reverse complement.")
    table = DNA_COMPLEMENT if sequence_type == "DNA" else RNA_COMPLEMENT
    return cleaned.translate(table)[::-1]


def transcribe(sequence):
    return validate_alphabet(sequence, "DNA").replace("T", "U")


def translate(sequence, *, frame=0, stop_at_stop=False):
    dna = clean_sequence(sequence).replace("U", "T")
    validate_alphabet(dna, "DNA")
    frame = int(frame)
    if frame not in {0, 1, 2}:
        raise ValueError("Frame must be 0, 1, or 2.")
    protein = []
    for index in range(frame, len(dna) - 2, 3):
        aa = CODON_TABLE.get(dna[index:index + 3], "X")
        if stop_at_stop and aa == "*":
            break
        protein.append(aa)
    return "".join(protein)


def find_orfs(sequence, *, minimum_codons=10):
    dna = validate_alphabet(clean_sequence(sequence).replace("U", "T"), "DNA")
    results = []
    for strand, strand_sequence in [(1, dna), (-1, reverse_complement(dna))]:
        for frame in range(3):
            index = frame
            while index <= len(strand_sequence) - 3:
                if strand_sequence[index:index + 3] != "ATG":
                    index += 3
                    continue
                end = index + 3
                while end <= len(strand_sequence) - 3:
                    codon = strand_sequence[end:end + 3]
                    if codon in {"TAA", "TAG", "TGA"}:
                        length_codons = (end + 3 - index) // 3
                        if length_codons >= int(minimum_codons):
                            start_pos = index if strand == 1 else len(dna) - (end + 3)
                            end_pos = end + 3 if strand == 1 else len(dna) - index
                            results.append({
                                "start": start_pos,
                                "end": end_pos,
                                "strand": strand,
                                "frame": frame,
                                "length_codons": length_codons,
                                "protein": translate(strand_sequence[index:end + 3]),
                            })
                        break
                    end += 3
                index += 3
    return sorted(results, key=lambda item: (item["start"], item["strand"]))


def gc_content(sequence):
    cleaned = clean_sequence(sequence).replace("U", "T")
    if not cleaned:
        return 0.0
    return round((cleaned.count("G") + cleaned.count("C")) * 100 / len(cleaned), 2)


def melting_temperature(sequence):
    dna = validate_alphabet(sequence, "DNA")
    if set(dna) - set("ACGT"):
        raise ValueError("Primer melting temperature requires unambiguous DNA bases.")
    if len(dna) < 14:
        return round(2 * (dna.count("A") + dna.count("T")) + 4 * (dna.count("G") + dna.count("C")), 2)
    return round(64.9 + 41 * ((dna.count("G") + dna.count("C")) - 16.4) / len(dna), 2)


def molecular_weight(sequence, sequence_type):
    cleaned = validate_alphabet(sequence, sequence_type)
    if sequence_type == "DNA":
        return round(len(cleaned) * 617.96 + 36.04, 2)
    if sequence_type == "RNA":
        return round(len(cleaned) * 340.5, 2)
    known = [AMINO_ACID_WEIGHTS[aa] for aa in cleaned if aa in AMINO_ACID_WEIGHTS]
    return round(sum(known) - max(0, len(known) - 1) * 18.015, 2)


def restriction_sites(sequence, enzyme_names=None):
    dna = validate_alphabet(sequence, "DNA")
    names = enzyme_names or list(RESTRICTION_ENZYMES)
    sites = []
    for name in names:
        enzyme = RESTRICTION_ENZYMES.get(name)
        if not enzyme:
            raise ValueError(f"Unknown restriction enzyme: {name}.")
        start = 0
        while True:
            found = dna.find(enzyme["site"], start)
            if found < 0:
                break
            sites.append({
                "enzyme": name,
                "site": enzyme["site"],
                "start": found,
                "end": found + len(enzyme["site"]),
                "cut": found + enzyme["cut"],
            })
            start = found + 1
    return sorted(sites, key=lambda item: (item["cut"], item["enzyme"]))


def virtual_digest(sequence, topology, enzyme_names):
    dna = validate_alphabet(sequence, "DNA")
    sites = restriction_sites(dna, enzyme_names)
    cuts = sorted(set(item["cut"] for item in sites))
    if not cuts:
        return {"sites": sites, "fragments": [{"start": 0, "end": len(dna), "length": len(dna)}]}
    fragments = []
    if topology == "CIRCULAR":
        for index, cut in enumerate(cuts):
            next_cut = cuts[(index + 1) % len(cuts)]
            length = (next_cut - cut) % len(dna)
            fragments.append({"start": cut, "end": next_cut, "length": length})
    else:
        boundaries = [0, *cuts, len(dna)]
        for start, end in zip(boundaries, boundaries[1:]):
            fragments.append({"start": start, "end": end, "length": end - start})
    return {"sites": sites, "fragments": fragments}
