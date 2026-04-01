"""
Modulo per la dashboard delle statistiche visiva.
Genera report statistici con grafici ASCII, barre di progresso e indicatori colorati.

Utilizza il modulo di persistenza per ottenere i dati.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from core.data_persistence import DataPersistence

# Configurazione logger
logger = logging.getLogger(__name__)

# ==================== COSTANTI ====================

# Simboli per barre di progresso
BARRA_PIENA = "█"
BARRA_VUOTA = "░"
BARRA_META = "▄"

# Colori (emoji)
INDICATORE_OK = "✅"
INDICATORE_ATTENZIONE = "🟡"
INDICATORE_ERRORE = "🔴"
INDICATORE_INFO = "🔵"

# Larghezza predefinita per i grafici
LARGHEZZA_GRAFICO_DEFAULT = 30


class StatisticheError(Exception):
    """Eccezione personalizzata per errori nelle statistiche."""
    pass


class StatisticheDashboard:
    """
    Classe per la generazione di statistiche e report visivi.
    Forniscegrafici ASCII, barre di progresso e tabelle formattate.
    """
    
    def __init__(self, persistence: DataPersistence):
        """
        Inizializza la dashboard delle statistiche.
        
        Args:
            persistence: Istanza del modulo di persistenza dati
        """
        self.persistence = persistence
        logger.info("Modulo StatisticheDashboard inizializzato")
    
    # ==================== METODI DI SUPPORTO ====================
    
    def _calcola_percentuale(self, parte: int, totale: int) -> float:
        """Calcola la percentuale, gestendo il caso di totale 0."""
        if totale == 0:
            return 0.0
        return round((parte / totale) * 100, 1)
    
    def _genera_barra_progresso(self, percentuale: int, larghezza: int = LARGHEZZA_GRAFICO_DEFAULT) -> str:
        """
        Genera una barra di progresso ASCII.
        
        Args:
            percentuale: Percentuale da visualizzare (0-100)
            larghezza: Numero di caratteri della barra
            
        Returns:
            Stringa rappresentante la barra di progresso
        """
        # Numero di blocchi pieni (arrotondato)
        blocchi_pieni = int((percentuale / 100) * larghezza)
        blocchi_vuoti = larghezza - blocchi_pieni
        
        return BARRA_PIENA * blocchi_pieni + BARRA_VUOTA * blocchi_vuoti
    
    def _calcola_tempo_medio_risoluzione(self, ticket_list: List[Dict]) -> Optional[float]:
        """
        Calcola il tempo medio di risoluzione dei ticket in ore.
        
        Args:
            ticket_list: Lista di ticket risolti
            
        Returns:
            Tempo medio in ore, o None se non calcolabile
        """
        tempi = []
        for ticket in ticket_list:
            # Verifica che il ticket sia risolto/chiuso
            stato = ticket.get("stato", "")
            if stato in ["risolto", "chiuso"]:
                data_creazione = ticket.get("data_creazione")
                data_chiusura = ticket.get("data_chiusura")
                
                if data_creazione and data_chiusura:
                    try:
                        dt_creazione = datetime.fromisoformat(data_creazione)
                        dt_chiusura = datetime.fromisoformat(data_chiusura)
                        delta = dt_chiusura - dt_creazione
                        tempi.append(delta.total_seconds() / 3600)  # Converti in ore
                    except Exception:
                        pass
        
        if tempi:
            return round(sum(tempi) / len(tempi), 1)
        return None
    
    # ==================== GRAFICI ASCII ====================
    
    def genera_grafico_barre(self, titolo: str, dati: Dict[str, int], 
                             larghezza: int = LARGHEZZA_GRAFICO_DEFAULT) -> str:
        """
        Genera un grafico a barre ASCII con etichette e percentuali.
        
        Args:
            titolo: Titolo del grafico
            dati: Dizionario con etichette e valori (es. {"Alta": 10, "Media": 5})
            larghezza: Larghezza massima delle barre
            
        Returns:
            Stringa formattata con il grafico
        """
        if not dati:
            return f"{titolo}:\n  Nessun dato disponibile"
        
        # Calcola il totale
        totale = sum(dati.values())
        
        # Trova la lunghezza massima dell'etichetta
        max_label_len = max(len(str(label)) for label in dati.keys())
        
        lines = []
        lines.append(f"\n{titolo}:")
        lines.append("-" * (max_label_len + larghezza + 15))
        
        # Ordina i dati per valore decrescente
        dati_ordinati = sorted(dati.items(), key=lambda x: x[1], reverse=True)
        
        for label, valore in dati_ordinati:
            percentuale = self._calcola_percentuale(valore, totale)
            barra = self._genera_barra_progresso(int(percentuale), larghezza)
            
            # Formatta la riga con allineamento
            riga = f"  {str(label):<{max_label_len}} {barra} {valore} ({percentuale}%)"
            lines.append(riga)
        
        lines.append("-" * (max_label_len + larghezza + 15))
        
        return "\n".join(lines)
    
    def genera_tabella_statistica(self, titolo: str, dati: Dict[str, Any], 
                                   colonna_valore: str = "valore") -> str:
        """
        Genera una tabella formattata per statistiche.
        
        Args:
            titolo: Titolo della tabella
            dati: Dizionario con i dati
            colonna_valore: Nome della colonna valore
            
        Returns:
            Stringa formattata come tabella
        """
        if not dati:
            return f"{titolo}:\n  Nessun dato disponibile"
        
        # Trova la lunghezza massima delle chiavi
        max_key_len = max(len(str(k)) for k in dati.keys())
        max_val_len = max(len(str(v)) for v in dati.values())
        
        lines = []
        lines.append(f"\n{titolo}:")
        lines.append("=" * (max_key_len + max_val_len + 7))
        
        for key, value in dati.items():
            lines.append(f"  {str(key):<{max_key_len}} | {value}")
        
        lines.append("=" * (max_key_len + max_val_len + 7))
        
        return "\n".join(lines)
    
    # ==================== STATISTICHE UTENTI ====================
    
    def get_statistiche_utenti(self) -> Dict[str, Any]:
        """
        Ottiene le statistiche relative agli utenti.
        
        Returns:
            Dizionario con le statistiche utenti:
            - totale: numero totale di utenti
            - attivi: utenti attivi
            - inattivi: utenti inattivi
            - con_lista: utenti con lista approvata
            - senza_lista: utenti senza lista
        """
        try:
            utenti = self.persistence.get_data("utenti", {})
            
            totale = len(utenti)
            attivi = sum(1 for u in utenti.values() if u.get("stato") == "attivo")
            inattivi = sum(1 for u in utenti.values() if u.get("stato") != "attivo")
            con_lista = sum(1 for u in utenti.values() if u.get("lista_approvata"))
            senza_lista = totale - con_lista
            
            return {
                "totale": totale,
                "attivi": attivi,
                "inattivi": inattivi,
                "con_lista": con_lista,
                "senza_lista": senza_lista,
                "percentuale_attivi": self._calcola_percentuale(attivi, totale) if totale > 0 else 0,
                "percentuale_con_lista": self._calcola_percentuale(con_lista, totale) if totale > 0 else 0
            }
        except Exception as e:
            logger.error(f"Errore nel calcolo statistiche utenti: {e}")
            return {
                "totale": 0,
                "attivi": 0,
                "inattivi": 0,
                "con_lista": 0,
                "senza_lista": 0,
                "percentuale_attivi": 0,
                "percentuale_con_lista": 0
            }
    
    def formatta_statistiche_utenti(self) -> str:
        """
        Formatta le statistiche utenti in modo visivo.
        
        Returns:
            Stringa formattata con le statistiche utenti
        """
        stats = self.get_statistiche_utenti()
        
        lines = []
        lines.append("\n" + "=" * 50)
        lines.append("📊 STATISTICHE UTENTI")
        lines.append("=" * 50)
        
        # Statistiche base
        indicator = INDICATORE_OK if stats["percentuale_attivi"] > 50 else INDICATORE_ATTENZIONE
        lines.append(f"\n{indicator} Totale Utenti: {stats['totale']}")
        
        # Barre di progresso per attivi/inattivi
        perc_attivi = int(stats["percentuale_attivi"])
        barra_attivi = self._genera_barra_progresso(perc_attivi)
        lines.append(f"   Attivi:    {barra_attivi} {perc_attivi}% ({stats['attivi']})")
        
        perc_inattivi = 100 - perc_attivi
        barra_inattivi = self._genera_barra_progresso(perc_inattivi)
        lines.append(f"   Inattivi:  {barra_inattivi} {perc_inattivi}% ({stats['inattivi']})")
        
        lines.append("")
        
        # Barre di progresso per lista
        perc_con_lista = int(stats["percentuale_con_lista"])
        barra_lista = self._genera_barra_progresso(perc_con_lista)
        lines.append(f"📋 Con Lista: {barra_lista} {perc_con_lista}% ({stats['con_lista']})")
        
        perc_senza_lista = 100 - perc_con_lista
        barra_senza_lista = self._genera_barra_progresso(perc_senza_lista)
        lines.append(f"📋 Senza Lista: {barra_senza_lista} {perc_senza_lista}% ({stats['senza_lista']})")
        
        lines.append("=" * 50)
        
        return "\n".join(lines)
    
    # ==================== STATISTICHE LISTE IPTV ====================
    
    def get_statistiche_liste(self) -> Dict[str, Any]:
        """
        Ottiene le statistiche relative alle liste IPTV.
        
        Returns:
            Dizionario con le statistiche liste:
            - totale: numero totale di liste
            - attive: liste attive
            - scadute: liste scadute
            - in_attesa: liste in attesa di approvazione
        """
        try:
            liste = self.persistence.get_data("liste_iptv", {})
            
            totale = len(liste)
            attive = sum(1 for l in liste.values() if l.get("stato") == "attiva")
            scadute = sum(1 for l in liste.values() if l.get("stato") == "scaduta")
            in_attesa = sum(1 for l in liste.values() if l.get("stato") == "in_attesa")
            inattive = totale - attive - scadute - in_attesa
            
            return {
                "totale": totale,
                "attive": attive,
                "scadute": scadute,
                "in_attesa": in_attesa,
                "inattive": inattive,
                "percentuale_attive": self._calcola_percentuale(attive, totale) if totale > 0 else 0,
                "percentuale_scadute": self._calcola_percentuale(scadute, totale) if totale > 0 else 0
            }
        except Exception as e:
            logger.error(f"Errore nel calcolo statistiche liste: {e}")
            return {
                "totale": 0,
                "attive": 0,
                "scadute": 0,
                "in_attesa": 0,
                "inattive": 0,
                "percentuale_attive": 0,
                "percentuale_scadute": 0
            }
    
    def formatta_statistiche_liste(self) -> str:
        """
        Formatta le statistiche liste IPTV in modo visivo.
        
        Returns:
            Stringa formattata con le statistiche liste
        """
        stats = self.get_statistiche_liste()
        
        lines = []
        lines.append("\n" + "=" * 50)
        lines.append("📡 STATISTICHE LISTE IPTV")
        lines.append("=" * 50)
        
        indicator = INDICATORE_OK if stats["percentuale_attive"] > 70 else INDICATORE_ATTENZIONE
        lines.append(f"\n{indicator} Totale Liste: {stats['totale']}")
        
        # Barre di stato liste
        if stats["totale"] > 0:
            # Attive
            perc_attive = int(stats["percentuale_attive"])
            barra_attive = self._genera_barra_progresso(perc_attive)
            lines.append(f"   Attive:    {barra_attive} {perc_attive}% ({stats['attive']})")
            
            # Scadute
            perc_scadute = int(stats["percentuale_scadute"])
            barra_scadute = self._genera_barra_progresso(perc_scadute)
            indicator_scad = INDICATORE_ERRORE if perc_scadute > 20 else INDICATORE_OK
            lines.append(f"   {indicator_scad} Scadute:   {barra_scadute} {perc_scadute}% ({stats['scadute']})")
            
            # In attesa
            perc_in_attesa = self._calcola_percentuale(stats["in_attesa"], stats["totale"])
            barra_in_attesa = self._genera_barra_progresso(int(perc_in_attesa))
            lines.append(f"   In Attesa: {barra_in_attesa} {perc_in_attesa}% ({stats['in_attesa']})")
            
            # Inattive
            perc_inattive = self._calcola_percentuale(stats["inattive"], stats["totale"])
            barra_inattive = self._genera_barra_progresso(int(perc_inattive))
            lines.append(f"   Inattive:  {barra_inattive} {perc_inattive}% ({stats['inattive']})")
        else:
            lines.append("\n   Nessuna lista registrata")
        
        lines.append("=" * 50)
        
        return "\n".join(lines)
    
    # ==================== STATISTICHE TICKET ====================
    
    def get_statistiche_ticket(self) -> Dict[str, Any]:
        """
        Ottiene le statistiche relative ai ticket.
        
        Returns:
            Dizionario con le statistiche ticket:
            - totale: numero totale di ticket
            - aperti: ticket aperti
            - in_lavorazione: ticket in lavorazione
            - risolti: ticket risolti
            - chiusi: ticket chiusi
            - per_priorità: dict con ticket per priorità
            - tempo_medio_risoluzione: tempo medio in ore
        """
        try:
            ticket = self.persistence.get_data("ticket", {})
            
            totale = len(ticket)
            aperti = sum(1 for t in ticket.values() if t.get("stato") == "aperto")
            in_lavorazione = sum(1 for t in ticket.values() if t.get("stato") == "in_lavorazione")
            risolti = sum(1 for t in ticket.values() if t.get("stato") == "risolto")
            chiusi = sum(1 for t in ticket.values() if t.get("stato") == "chiuso")
            riaperti = sum(1 for t in ticket.values() if t.get("stato") == "riaperto")
            
            # Ticket per priorità
            per_priorità = {
                "alta": sum(1 for t in ticket.values() if t.get("priorità") == "alta"),
                "media": sum(1 for t in ticket.values() if t.get("priorità") == "media"),
                "bassa": sum(1 for t in ticket.values() if t.get("priorità") == "bassa")
            }
            
            # Tempo medio di risoluzione
            ticket_list = list(ticket.values())
            tempo_medio = self._calcola_tempo_medio_risoluzione(ticket_list)
            
            return {
                "totale": totale,
                "aperti": aperti,
                "in_lavorazione": in_lavorazione,
                "risolti": risolti,
                "chiusi": chiusi,
                "riaperti": riaperti,
                "per_priorità": per_priorità,
                "tempo_medio_risoluzione": tempo_medio,
                "percentuale_risolti": self._calcola_percentuale(risolti + chiusi, totale) if totale > 0 else 0
            }
        except Exception as e:
            logger.error(f"Errore nel calcolo statistiche ticket: {e}")
            return {
                "totale": 0,
                "aperti": 0,
                "in_lavorazione": 0,
                "risolti": 0,
                "chiusi": 0,
                "riaperti": 0,
                "per_priorità": {"alta": 0, "media": 0, "bassa": 0},
                "tempo_medio_risoluzione": None,
                "percentuale_risolti": 0
            }
    
    def formatta_statistiche_ticket(self) -> str:
        """
        Formatta le statistiche ticket in modo visivo.
        
        Returns:
            Stringa formattata con le statistiche ticket
        """
        stats = self.get_statistiche_ticket()
        
        lines = []
        lines.append("\n" + "=" * 50)
        lines.append("🎫 STATISTICHE TICKET")
        lines.append("=" * 50)
        
        indicator = INDICATORE_OK if stats["percentuale_risolti"] > 70 else INDICATORE_ATTENZIONE
        lines.append(f"\n{indicator} Totale Ticket: {stats['totale']}")
        
        # Statistiche per stato
        lines.append("\n📌 Per Stato:")
        lines.append(f"   Aperti:         {stats['aperti']}")
        lines.append(f"   In Lavorazione: {stats['in_lavorazione']}")
        lines.append(f"   Risolti:        {stats['risolti']}")
        lines.append(f"   Chiusi:         {stats['chiusi']}")
        lines.append(f"   Riaperte:       {stats['riaperti']}")
        
        # Grafico per priorità
        if stats["totale"] > 0:
            lines.append("\n🎯 Per Priorità:")
            lines.append(self.genera_grafico_barre("Priorità", stats["per_priorità"], 20))
        
        # Tempo medio risoluzione
        if stats["tempo_medio_risoluzione"] is not None:
            tempo = stats["tempo_medio_risoluzione"]
            indicator_tempo = INDICATORE_OK if tempo < 24 else INDICATORE_ATTENZIONE if tempo < 72 else INDICATORE_ERRORE
            lines.append(f"\n⏱️ Tempo Medio Risoluzione: {indicator_tempo} {tempo} ore")
        else:
            lines.append(f"\n⏱️ Tempo Medio Risoluzione: Nessun dato")
        
        lines.append("=" * 50)
        
        return "\n".join(lines)
    
    # ==================== STATISTICHE RICHIESTE ====================
    
    def get_statistiche_richieste(self) -> Dict[str, Any]:
        """
        Ottiene le statistiche relative alle richieste.
        
        Returns:
            Dizionario con le statistiche richieste:
            - totale: numero totale di richieste
            - in_attesa: richieste in attesa
            - approvate: richieste approvate
            - rifiutate: richieste rifiutate
        """
        try:
            richieste = self.persistence.get_data("richieste", [])
            
            totale = len(richieste)
            in_attesa = sum(1 for r in richieste if r.get("stato") == "in_attesa")
            approvate = sum(1 for r in richieste if r.get("stato") == "approvata")
            rifiutate = sum(1 for r in richieste if r.get("stato") == "rifiutata")
            
            return {
                "totale": totale,
                "in_attesa": in_attesa,
                "approvate": approvate,
                "rifiutate": rifiutate,
                "percentuale_approvate": self._calcola_percentuale(approvate, totale) if totale > 0 else 0,
                "percentuale_rifiutate": self._calcola_percentuale(rifiutate, totale) if totale > 0 else 0
            }
        except Exception as e:
            logger.error(f"Errore nel calcolo statistiche richieste: {e}")
            return {
                "totale": 0,
                "in_attesa": 0,
                "approvate": 0,
                "rifiutate": 0,
                "percentuale_approvate": 0,
                "percentuale_rifiutate": 0
            }
    
    def formatta_statistiche_richieste(self) -> str:
        """
        Formatta le statistiche richieste in modo visivo.
        
        Returns:
            Stringa formattata con le statistiche richieste
        """
        stats = self.get_statistiche_richieste()
        
        lines = []
        lines.append("\n" + "=" * 50)
        lines.append("📝 STATISTICHE RICHIESTE")
        lines.append("=" * 50)
        
        indicator = INDICATORE_INFO
        lines.append(f"\n{indicator} Totale Richieste: {stats['totale']}")
        
        if stats["totale"] > 0:
            # Barre di stato richieste
            perc_in_attesa = self._calcola_percentuale(stats["in_attesa"], stats["totale"])
            barra_in_attesa = self._genera_barra_progresso(int(perc_in_attesa))
            lines.append(f"   ⏳ In Attesa:  {barra_in_attesa} {perc_in_attesa}% ({stats['in_attesa']})")
            
            perc_approvate = int(stats["percentuale_approvate"])
            barra_approvate = self._genera_barra_progresso(perc_approvate)
            indicator_app = INDICATORE_OK if perc_approvate > 50 else INDICATORE_ATTENZIONE
            lines.append(f"   {indicator_app} Approvate:  {barra_approvate} {perc_approvate}% ({stats['approvate']})")
            
            perc_rifiutate = int(stats["percentuale_rifiutate"])
            barra_rifiutate = self._genera_barra_progresso(perc_rifiutate)
            indicator_rif = INDICATORE_ERRORE if perc_rifiutate > 30 else INDICATORE_OK
            lines.append(f"   {indicator_rif} Rifiutate:  {barra_rifiutate} {perc_rifiutate}% ({stats['rifiutate']})")
        else:
            lines.append("\n   Nessuna richiesta registrata")
        
        lines.append("=" * 50)
        
        return "\n".join(lines)
    
    # ==================== STATISTICHE SISTEMA ====================
    
    def get_statistiche_sistema(self) -> Dict[str, Any]:
        """
        Ottiene le statistiche relative al sistema.
        
        Returns:
            Dizionario con le statistiche sistema:
            - uptime: percentuale uptime
            - ultimo_backup: data ultimo backup
            - backup_count: numero backup totali
            - rate_limit_attivo: se il rate limiting è attivo
        """
        try:
            # Prova a ottenere info dal backup system se disponibile
            stato_backup = {
                "ultimo_backup": None,
                "backup_count": 0,
                "backup_locali": 0,
                "backup_cloud": 0
            }
            
            try:
                from modules.backup_system import BackupSystem
                # Prova a ottenere lo stato (senza istanziare per evitare dipendenze)
                backup_data = self.persistence.get_data("backup", {})
                if backup_data:
                    storico = backup_data.get("storico", [])
                    stato_backup["backup_count"] = len(storico)
                    stato_backup["ultimo_backup"] = storico[-1].get("timestamp") if storico else None
                    stato_backup["backup_locali"] = sum(1 for b in storico if b.get("tipo") == "locale")
                    stato_backup["backup_cloud"] = sum(1 for b in storico if b.get("tipo") == "cloud")
            except Exception as e:
                logger.debug(f"Impossibile ottenere info backup: {e}")
            
            # Rate limit info
            rate_limit_data = self.persistence.get_data("rate_limits", {})
            rate_limit_count = len(rate_limit_data)
            
            return {
                "uptime": 99.9,  # Valore simulato, in produzione collegare a stato_servizio
                "ultimo_backup": stato_backup["ultimo_backup"],
                "backup_count": stato_backup["backup_count"],
                "backup_locali": stato_backup["backup_locali"],
                "backup_cloud": stato_backup["backup_cloud"],
                "rate_limit_attivi": rate_limit_count,
                "timestamp_check": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Errore nel calcolo statistiche sistema: {e}")
            return {
                "uptime": 0,
                "ultimo_backup": None,
                "backup_count": 0,
                "backup_locali": 0,
                "backup_cloud": 0,
                "rate_limit_attivi": 0,
                "timestamp_check": datetime.now().isoformat()
            }
    
    def formatta_statistiche_sistema(self) -> str:
        """
        Formatta le statistiche sistema in modo visivo.
        
        Returns:
            Stringa formattata con le statistiche sistema
        """
        stats = self.get_statistiche_sistema()
        
        lines = []
        lines.append("\n" + "=" * 50)
        lines.append("⚙️ STATISTICHE SISTEMA")
        lines.append("=" * 50)
        
        # Uptime
        uptime = stats.get("uptime", 0)
        indicator_uptime = INDICATORE_OK if uptime > 95 else INDICATORE_ATTENZIONE if uptime > 90 else INDICATORE_ERRORE
        barra_uptime = self._genera_barra_progresso(int(uptime))
        lines.append(f"\n{indicator_uptime} Uptime: {barra_uptime} {uptime}%")
        
        # Backup
        lines.append("\n💾 Backup:")
        lines.append(f"   Totale: {stats['backup_count']}")
        lines.append(f"   Locali: {stats['backup_locali']}")
        lines.append(f"   Cloud:  {stats['backup_cloud']}")
        
        if stats["ultimo_backup"]:
            try:
                dt = datetime.fromisoformat(stats["ultimo_backup"])
                lines.append(f"   Ultimo: {dt.strftime('%d/%m/%Y %H:%M')}")
            except Exception:
                lines.append(f"   Ultimo: {stats['ultimo_backup']}")
        else:
            lines.append(f"   Ultimo: Mai eseguito")
        
        # Rate limiting
        lines.append(f"\n🛡️ Rate Limiting:")
        lines.append(f"   Utenti Monitorati: {stats['rate_limit_attivi']}")
        
        # Timestamp
        lines.append(f"\n📅 Ultimo Check: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        
        lines.append("=" * 50)
        
        return "\n".join(lines)
    
    # ==================== STATISTICHE COMPLETE ====================
    
    def get_statistiche_complete(self) -> Dict[str, Any]:
        """
        Ottiene tutte le statistiche combinate.
        
        Returns:
            Dizionario con tutte le statistiche:
            - utenti, liste, ticket, richieste, sistema
        """
        return {
            "utenti": self.get_statistiche_utenti(),
            "liste": self.get_statistiche_liste(),
            "ticket": self.get_statistiche_ticket(),
            "richieste": self.get_statistiche_richieste(),
            "sistema": self.get_statistiche_sistema(),
            "timestamp": datetime.now().isoformat()
        }
    
    def genera_report(self) -> str:
        """
        Genera un report completo formattato con tutte le statistiche.
        
        Returns:
            Stringa formattata con il report completo
        """
        lines = []
        
        # Header
        lines.append("\n" + "=" * 60)
        lines.append("║        📊 DASHBOARD STATISTICHE HELPERBOT        ║")
        lines.append("=" * 60)
        lines.append(f"📅 Report generato: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        
        # Statistiche Utenti
        lines.append(self.formatta_statistiche_utenti())
        
        # Statistiche Liste IPTV
        lines.append(self.formatta_statistiche_liste())
        
        # Statistiche Ticket
        lines.append(self.formatta_statistiche_ticket())
        
        # Statistiche Richieste
        lines.append(self.formatta_statistiche_richieste())
        
        # Statistiche Sistema
        lines.append(self.formatta_statistiche_sistema())
        
        # Footer
        lines.append("\n" + "=" * 60)
        lines.append("║              FINE REPORT STATISTICO              ║")
        lines.append("=" * 60 + "\n")
        
        return "\n".join(lines)
    
    def genera_report_completo(self) -> str:
        """
        Genera un report completo delle statistiche.
        Metodo alias per genera_report() per compatibilità con il menu admin.
        
        Returns:
            Stringa formattata con il report completo
        """
        return self.genera_report()
    
    # ==================== METODI AGGIUNTIVI ====================
    
    def genera_grafico_categorie(self, titolo: str, categorie: Dict[str, int], 
                                  larghezza: int = LARGHEZZA_GRAFICO_DEFAULT) -> str:
        """
        Genera un grafico per categorie con supporto emoji.
        
        Args:
            titolo: Titolo del grafico
            categorie: Dizionario categorie -> count
            larghezza: Larghezza barre
            
        Returns:
            Grafico formattato
        """
        if not categorie:
            return f"{titolo}: Nessun dato"
        
        totale = sum(categorie.values())
        
        emoji_map = {
            "alta": "🔴",
            "media": "🟡",
            "bassa": "🟢",
            "attivo": "✅",
            "inattivo": "❌",
            "aperto": "📂",
            "chiuso": "📁",
            "approvata": "✅",
            "rifiutata": "❌",
            "in_attesa": "⏳"
        }
        
        lines = [f"\n{titolo}"]
        lines.append("-" * (larghezza + 30))
        
        for cat, count in sorted(categorie.items(), key=lambda x: x[1], reverse=True):
            perc = self._calcola_percentuale(count, totale)
            barra = self._genera_barra_progresso(int(perc), larghezza)
            emoji = emoji_map.get(cat.lower(), "📊")
            lines.append(f"  {emoji} {cat}: {barra} {perc}% ({count})")
        
        lines.append("-" * (larghezza + 30))
        
        return "\n".join(lines)
    
    def genera_sommario_kpi(self) -> str:
        """
        Genera un sommario KPI (Key Performance Indicators).
        
        Returns:
            Stringa con i principali KPI
        """
        stats = self.get_statistiche_complete()
        
        lines = []
        lines.append("\n" + "=" * 50)
        lines.append("📈 SOMMARIO KPI (Key Performance Indicators)")
        lines.append("=" * 50)
        
        # KPI Utenti
        u = stats["utenti"]
        lines.append(f"\n👥 Utenti: {u['totale']} | Attivi: {u['percentuale_attivi']}%")
        
        # KPI Liste
        l = stats["liste"]
        lines.append(f"📡 Liste:  {l['totale']} | Attive: {l['percentuale_attive']}%")
        
        # KPI Ticket
        t = stats["ticket"]
        lines.append(f"🎫 Ticket: {t['totale']} | Risolti: {t['percentuale_risolti']}%")
        if t["tempo_medio_risoluzione"]:
            lines.append(f"   ⏱️ Tempo Medio: {t['tempo_medio_risoluzione']}h")
        
        # KPI Richieste
        r = stats["richieste"]
        lines.append(f"📝 Richieste: {r['totale']} | Approvate: {r['percentuale_approvate']}%")
        
        # KPI Sistema
        s = stats["sistema"]
        indicator = INDICATORE_OK if s['uptime'] > 95 else INDICATORE_ATTENZIONE
        lines.append(f"⚙️ Sistema: Uptime {indicator}{s['uptime']}% | Backup: {s['backup_count']}")
        
        lines.append("=" * 50)
        
        return "\n".join(lines)


# ==================== FUNZIONI DI UTILITY ====================

def formatta_numero_grande(numero: int) -> str:
    """
    Formatta un numero grande con separatori di migliaia.
    
    Args:
        numero: Numero da formattare
        
    Returns:
        Stringa formattata
    """
    return f"{numero:,}".replace(",", ".")


def genera_barra_emoji(percentuale: float) -> str:
    """
    Genera una barra di progresso usando emoji.
    
    Args:
        percentuale: Percentuale (0-100)
        
    Returns:
        Stringa con barra emoji
    """
    emoji_piena = "🟩"
    emoji_vuota = "⬜"
    
    # 10 segmenti
    segmenti = int(percentuale / 10)
    return emoji_piena * segmenti + emoji_vuota * (10 - segmenti)


# ==================== MAIN PER TEST ====================

if __name__ == "__main__":
    # Test del modulo
    print("Test modulo statistiche dashboard...")
    
    # Crea una persistenza fittizia per il test
    persistence = DataPersistence()
    
    # Crea la dashboard
    dashboard = StatisticheDashboard(persistence)
    
    # Genera il report completo
    report = dashboard.genera_report()
    print(report)
    
    # Test sommaro KPI
    kpi = dashboard.genera_sommario_kpi()
    print(kpi)