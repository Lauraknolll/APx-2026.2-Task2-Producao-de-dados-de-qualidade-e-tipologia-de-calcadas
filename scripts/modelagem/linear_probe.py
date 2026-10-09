import os
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, accuracy_score, confusion_matrix
import matplotlib.pyplot as plt
import seaborn as sns

def evaluate_model(model, features, labels, split_name):
    predictions = model.predict(features)
    acc = accuracy_score(labels, predictions)
    print(f"\n--- Resultados no conjunto de {split_name.upper()} ---")
    print(f"Acurácia: {acc:.4f}")
    print("\nRelatório de Classificação:")
    target_names = ["Adequada (0)", "Inadequada (1)", "Sem calçada (2)", "Não identificável (3)"]
    print(classification_report(labels, predictions, labels=[0, 1, 2, 3], target_names=target_names, zero_division=0))
    
    return confusion_matrix(labels, predictions, labels=[0, 1, 2, 3])

def main():
    DATA_DIR = "data/processed/apx2-bzsou-v2"
    
    # 1. Carregar as features e labels extraídas
    print("Carregando features extraídas pelo DINOv2...")
    try:
        X_train = np.load(os.path.join(DATA_DIR, "train_features.npy"))
        y_train = np.load(os.path.join(DATA_DIR, "train_labels.npy"))
        
        X_valid = np.load(os.path.join(DATA_DIR, "valid_features.npy"))
        y_valid = np.load(os.path.join(DATA_DIR, "valid_labels.npy"))
        
        X_test = np.load(os.path.join(DATA_DIR, "test_features.npy"))
        y_test = np.load(os.path.join(DATA_DIR, "test_labels.npy"))
    except FileNotFoundError as e:
        print(f"[ERRO] Arquivos não encontrados: {e}. Rode o script de extração primeiro!")
        return

    print(f"Dimensões de Treino: {X_train.shape} (Features), {y_train.shape} (Labels)")
    
    # 2. Treinar o modelo linear (Linear Probing)
    print("\nTreinando Regressão Logística (Linear Probe)...")
    # max_iter aumentado pois o DINOv2 Large gera features complexas
    # class_weight='balanced' ajuda caso tenhamos muitas mais calçadas de um tipo do que do outro
    clf = LogisticRegression(max_iter=1000, class_weight='balanced', random_state=42)
    clf.fit(X_train, y_train)
    
    # 3. Avaliar nos conjuntos de validação e teste
    cm_valid = evaluate_model(clf, X_valid, y_valid, "Validação")
    cm_test = evaluate_model(clf, X_test, y_test, "Teste")
    
    # 4. Salvar matriz de confusão do Teste para visualização (opcional)
    os.makedirs("data/reports", exist_ok=True)
    plt.figure(figsize=(6,5))
    sns.heatmap(cm_test, annot=True, fmt='d', cmap='Blues', 
                xticklabels=["Adequada", "Inadequada", "Sem calçada", "Não id."], 
                yticklabels=["Adequada", "Inadequada", "Sem calçada", "Não id."])
    plt.title('Matriz de Confusão (Teste)')
    plt.ylabel('Verdadeiro')
    plt.xlabel('Previsto')
    plt.tight_layout()
    plt.savefig("data/reports/confusion_matrix_test.png")
    print("\nMatriz de confusão salva em: data/reports/confusion_matrix_test.png")
    print("✅ Treinamento finalizado com sucesso!")

if __name__ == "__main__":
    main()
