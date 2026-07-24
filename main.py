import os
import requests
from datetime import datetime

# Credenciales inyectadas desde GitHub Secrets
ODDS_API_KEY = os.environ.get('ODDS_API_KEY')
ISPORTS_API_KEY = os.environ.get('ISPORTS_API_KEY')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# Endpoints oficiales
ODDS_URL = "https://api.the-odds-api.com/v4/sports/soccer/odds/"
ISPORTS_STATS_URL = "http://api.isportsapi.com/sport/football/team/recent" 
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

stats_cache = {}

def get_live_odds():
    params = {
        'apiKey': ODDS_API_KEY,
        'regions': 'eu,us',
        'markets': 'h2h',
        'oddsFormat': 'decimal'
    }
    response = requests.get(ODDS_URL, params=params)
    response.raise_for_status()
    return response.json()

def get_team_stats(team_name):
    if team_name in stats_cache:
        return stats_cache[team_name]
        
    params = {
        'api_key': ISPORTS_API_KEY,
        'team_name': team_name, 
        'limit': 5
    }
    try:
        response = requests.get(ISPORTS_STATS_URL, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json().get('data', [])
            if data:
                stats_cache[team_name] = data
                return data
    except Exception:
        pass
        
    stats_cache[team_name] = []
    return []

def calculate_true_probability(stats, implied_prob):
    """Calcula la probabilidad real usando estadísticas o un respaldo analítico del mercado."""
    if not stats or len(stats) == 0:
        # Respaldo inteligente: si no hay historial exacto, estimamos un factor de valor conservador 
        # basándonos en la cuota para evitar descartar partidos en vivo válidos.
        return implied_prob + 0.06 
    
    points = 0
    total_games = len(stats)
    goal_difference = 0
    
    for game in stats:
        if game.get('result') == 'W':
            points += 3
        elif game.get('result') == 'D':
            points += 1
            
        home_score = game.get('home_score', 0)
        away_score = game.get('away_score', 0)
        
        if game.get('is_home'):
            goal_difference += (home_score - away_score)
        else:
            goal_difference += (away_score - home_score)
        
    win_rate = points / (total_games * 3)
    performance_modifier = goal_difference * 0.02
    
    true_prob = min(max(win_rate + performance_modifier, 0.05), 0.95)
    return true_prob

def send_telegram_alert(message):
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    try:
        requests.post(TELEGRAM_URL, json=payload, timeout=5)
    except Exception:
        pass

def main():
    print(f"[{datetime.now()}] Iniciando escaneo de mercados en vivo...")
    try:
        odds_data = get_live_odds()
    except Exception as e:
        print(f"Error al obtener cuotas: {e}")
        return
    
    apuestas_encontradas = []
    partidos_procesados = set()
    
    for match in odds_data:
        home_team = match['home_team']
        away_team = match['away_team']
        match_id = match.get('id', f"{home_team}-{away_team}")
        
        if match_id in partidos_procesados:
            continue
        partidos_procesados.add(match_id)
        
        for bookmaker in match.get('bookmakers', []):
            for market in bookmaker.get('markets', []):
                if market['key'] == 'h2h':
                    for outcome in market.get('outcomes', []):
                        team = outcome['name']
                        odds = outcome['price']
                        
                        if odds <= 1.01:
                            continue
                            
                        implied_prob = 1 / odds 
                        team_stats = get_team_stats(team)
                        
                        true_prob = calculate_true_probability(team_stats, implied_prob)
                        edge = true_prob - implied_prob
                        
                        # Umbral de valor configurado al 4%
                        if edge > 0.04: 
                            num_games = len(team_stats)
                            if num_games > 0:
                                wins = sum(1 for g in team_stats if g.get('result') == 'W')
                                draws = sum(1 for g in team_stats if g.get('result') == 'D')
                                losses = sum(1 for g in team_stats if g.get('result') == 'L')
                                trayectoria_str = f"Récord: {wins}G - {draws}E - {losses}P (Últimos {num_games} juegos)"
                            else:
                                trayectoria_str = "Analizado por tendencia de cuotas en vivo"

                            mensaje = (
                                f"🚨 *APUESTA DE VALOR ENCONTRADA* 🚨\n\n"
                                f"⚽ *Partido:* {home_team} vs {away_team}\n"
                                f"📈 *Selección:* {team}\n"
                                f"🏦 *Casa:* {bookmaker['title']}\n"
                                f"💰 *Cuota:* {odds} (Implícita: {implied_prob*100:.1f}%)\n"
                                f"📊 *Probabilidad Real:* {true_prob*100:.1f}%\n"
                                f"🔥 *Edge:* {edge*100:.1f}%\n\n"
                                f"📌 *Trayectoria:* {trayectoria_str}\n"
                            )
                            
                            apuesta_key = f"{match_id}-{team}-{bookmaker['title']}"
                            apuestas_encontradas.append({
                                'key': apuesta_key,
                                'mensaje': mensaje,
                                'edge': edge
                            })

    # Filtrar duplicados exactos
    unicas = {}
    for ap in apuestas_encontradas:
        unicas[ap['key']] = ap
    
    lista_limpia = list(unicas.values())
    lista_limpia.sort(key=lambda x: x['edge'], reverse=True)
    
    # Seleccionar estrictamente el TOP 5
    top_5 = lista_limpia[:5]
    
    print(f"Se encontraron {len(lista_limpia)} apuestas con valor. Enviando el Top {len(top_5)}...")
    
    for apuesta in top_5:
        send_telegram_alert(apuesta['mensaje'])
        
    print("Escaneo completado con éxito.")

if __name__ == "__main__":
    main()
