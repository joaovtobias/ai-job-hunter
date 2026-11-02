import requests
from scrapy import Selector

headers = {
    'accept': 'application/json',
    'accept-language': 'en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7',
    'content-type': 'application/json',
    'origin': 'https://www.ciadetalentos.com.br',
    'priority': 'u=1, i',
    'referer': 'https://www.ciadetalentos.com.br/',
    'sec-ch-ua': '"Chromium";v="154", "Google Chrome";v="154", "Not A(Brand";v="99"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-site',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36',
}

json_data = {
    'locale': 'pt',
}

response = requests.post(
    'https://vagas.ciadetalentos.com.br/applicant/rest/applicant/authentication/filter',
    headers=headers,
    json=json_data,
)

dados = response.json()

url = 'https://www.ciadeestagios.com.br/vagas-de-estagio/#vagas'

html = requests.get(url).content

response = Selector(text = html)

links = response.css('a.button.button--green.button--md.button--full-width::attr(href)').getall()

for link in links:
    with open('vagas.txt','a',encoding = 'utf-8') as arquivo:
        arquivo.write(link + '\n')

for vaga in dados:
    nome_vaga = vaga['opportunityName']
    local_vaga = vaga['opportunityLocations']
    area_vaga = vaga['opportunityAreas']
    empresa_vaga = vaga['companyName']
    tempo = vaga['daysRemainingForInscription']

    with open('vagas.txt', 'a', encoding='utf-8') as arquivo:
        arquivo.write(f"{nome_vaga}\n{local_vaga}\n{area_vaga.replace('Área','Area')}\n{empresa_vaga}\n{tempo}\n\n")