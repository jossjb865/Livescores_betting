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

def get_live_odds():
    """Obtiene las cuotas en vivo de las casas de apuestas."""
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
    """Obtiene los últimos 5 partidos y el rendimiento real desde iSportsAPI."""
    params = {
        'api_key': ISPORTS_API_KEY,
        'team_name': team_name, 
        'limit': 5
    }
    response = requests.get(ISPORTS_STATS_URL, params=params)
    if response.status_code == 200:
        # Nota: Ajusta las llaves del JSON según la liga específica consultada en iSportsAPI
        return response.json().get('data', [])
    return []

def calculate_true_probability(stats):
    """Calcula la probabilidad real de victoria basándose en la trayectoria reciente."""
    if not stats:
        return 0.33 # Probabilidad base neutra si no hay datos disponibles
    
    points = 0
    total_games = len(stats)
    goal_difference = 0
    
    for game in stats:
        # Ponderación de resultados (Win/Draw/Loss)
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
    # Modificador de rendimiento basado en el dominio de goles recientes
    performance_modifier = goal_difference * 0.02
    
    # La probabilidad real debe mantenerse dentro de límites lógicos
    true_prob = min(max(win_rate + performance_modifier, 0.05), 0.95)
    return true_prob

def send_telegram_alert(message):
    """Despacha el mensaje estructurado al bot de Telegram."""
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    requests.post(TELEGRAM_URL, json=payload)

def main():
    print(f"[{datetime.now()}] Iniciando escaneo de mercados en vivo...")
    odds_data = get_live_odds()
    
    for match in odds_data:
        home_team = match['home_team']
        away_team = match['away_team']
        
        for bookmaker in match['bookmakers']:
            for market in bookmaker['markets']:
                if market['key'] == 'h2h':
                    for outcome in market['outcomes']:
                        team = outcome['name']
                        odds = outcome['price']
                        
                        # Probabilidad según la casa de apuestas
                        implied_prob = 1 / odds 
                        
                        # Obtención de trayectoria y cálculo matemático
                        team_stats = get_team_stats(team)
                        true_prob = calculate_true_probability(team_stats)
                        
                        # Edge (Valor): Diferencia matemática a tu favor
                        edge = true_prob - implied_prob
                        
                        # Umbral configurado al 5% de ventaja
                        if edge > 0.05: 
                            wins = sum(1 for g in team_stats if g.get('result') == 'W')
                            draws = sum(1 for g in team_stats if g.get('result') == 'D')
                            losses = sum(1 for g in team_stats if g.get('result') == 'L')
                            
                            mensaje = (
                                f"🚨 *APUESTA DE VALOR ENCONTRADA* 🚨\n\n"
                                f"⚽ *Partido:* {home_team} vs {away_team}\n"
                                f"📈 *Selección:* {team}\n"
                                f"🏦 *Casa:* {bookmaker['title']}\n"
                                f"💰 *Cuota:* {odds} (Implícita: {implied_prob*100:.1f}%)\n"
                                f"📊 *Probabilidad Real:* {true_prob*100:.1f}%\n"
                                f"🔥 *Edge:* {edge*100:.1f}%\n\n"
                                f"📌 *Trayectoria (Últimos {len(team_stats)} juegos):*\n"
                                f"Récord: {wins}G - {draws}E - {losses}P\n"
                            )
                            send_telegram_alert(mensaje)
                            print(f"Alerta despachada: {team} @ {odds}")

if __name__ == "__main__":
    main()
