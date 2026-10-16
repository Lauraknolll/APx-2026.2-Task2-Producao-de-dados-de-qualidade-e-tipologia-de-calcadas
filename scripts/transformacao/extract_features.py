import os
import json
import torch
import numpy as np
from PIL import Image
from transformers import AutoImageProcessor, AutoModel
from tqdm import tqdm

def process_split(split_name, base_dir, processor, model, device):
    split_dir = os.path.join(base_dir, split_name)
    json_path = os.path.join(split_dir, "_annotations.coco.json")
    
    if not os.path.exists(json_path):
        print(f"[{split_name}] Anotações não encontradas, pulando...")
        return None, None
        
    with open(json_path, 'r') as f:
        coco_data = json.load(f)
        
    # Mapear os IDs de todas as categorias
    cat_ids = {}
    for cat in coco_data.get('categories', []):
        cat_ids[cat['name']] = cat['id']
            
    # Mapear quais categorias cada imagem possui
    img_to_cats = {}
    for ann in coco_data.get('annotations', []):
        img_id = ann['image_id']
        cat_id = ann['category_id']
        img_to_cats.setdefault(img_id, set()).add(cat_id)
        
    features_list = []
    labels_list = []
    
    # Processar cada imagem listada
    print(f"Extraindo features em '{split_name}'...")
    for img_info in tqdm(coco_data['images']):
        img_id = img_info['id']
        
        cats = img_to_cats.get(img_id, set())
        if not cats:
            continue # Ignora se não tiver nenhuma anotação
            
        # Regra de Prioridade:
        # 1. Não identificável (Classe 3)
        # 2. Sem calçada (Classe 2)
        # 3. Inadequada (Classe 1)
        # 4. Adequada (Classe 0)
        
        id_nao = cat_ids.get('Nao identificavel')
        id_sem = cat_ids.get('Sem calcada')
        id_inadequada = cat_ids.get('Inadequada')
        id_adequada = cat_ids.get('Adequada')
        
        if id_nao and id_nao in cats:
            label = 3
        elif id_sem and id_sem in cats:
            label = 2
        elif id_inadequada and id_inadequada in cats:
            label = 1
        elif id_adequada and id_adequada in cats:
            label = 0
        else:
            continue
            
        img_filename = img_info['file_name']
        img_path = os.path.join(split_dir, img_filename)
        
        try:
            image = Image.open(img_path).convert("RGB")
            
            # Pré-processamento e inferência
            inputs = processor(images=image, return_tensors="pt").to(device)
            with torch.no_grad():
                outputs = model(**inputs)
                
            # O DINOv2 retorna a last_hidden_state. O token [CLS] (índice 0) contém a feature global da imagem.
            cls_token = outputs.last_hidden_state[:, 0, :].cpu().numpy()
            
            features_list.append(cls_token)
            labels_list.append(label)
        except Exception as e:
            print(f"Erro processando {img_filename}: {e}")
            
    if not features_list:
        return None, None
        
    # Juntar todos os vetores num único array (N, Embed_Dim)
    features_array = np.vstack(features_list)
    labels_array = np.array(labels_list)
    
    return features_array, labels_array

def main():
    # Configurações de caminhos
    DATASET_DIR = "data/raw/apx2-bzsou-v2"
    OUTPUT_DIR = f"data/processed/{os.path.basename(DATASET_DIR)}"
    MODEL_ID = "projectsidewalk/sidewalk-validator-ai-surfaceproblem"
    
    if not os.path.exists(DATASET_DIR):
        print(f"[ERRO] Diretório do dataset não encontrado em {DATASET_DIR}. Rode o script de download primeiro!")
        return
        
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Iniciando extração. Usando dispositivo: {device}")
    
    print(f"Baixando/Carregando modelo '{MODEL_ID}' do HuggingFace...")
    # Carrega automaticamente do Hugging Face. Na primeira vez ele baixa, nas seguintes usa cache.
    processor = AutoImageProcessor.from_pretrained(MODEL_ID)
    model = AutoModel.from_pretrained(MODEL_ID).to(device)
    model.eval()
    
    # Processa os 3 splits (se existirem)
    splits = ["train", "valid", "test"]
    for split in splits:
        feat, lbl = process_split(split, DATASET_DIR, processor, model, device)
        if feat is not None:
            # Salvar no formato do numpy (.npy) para ficar muito rápido e fácil de carregar depois no scikit-learn
            feat_path = os.path.join(OUTPUT_DIR, f"{split}_features.npy")
            lbl_path = os.path.join(OUTPUT_DIR, f"{split}_labels.npy")
            np.save(feat_path, feat)
            np.save(lbl_path, lbl)
            print(f"[{split}] Salvo: {feat.shape[0]} amostras, cada uma com vetor de tamanho {feat.shape[1]}")
            
    print("\n✅ Extração concluída! Os vetores estão em 'data/processed/' prontos para o treino rápido do Linear Probing.")

if __name__ == "__main__":
    main()
