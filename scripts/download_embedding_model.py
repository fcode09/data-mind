"""Explicit download of MIT-licensed multilingual-e5-small with pinned SHA256."""
import argparse
from pathlib import Path
from download_models import acquire
REVISION = '614241f622f53c4eeff9890bdc4f31cfecc418b3'
FILES = [{'path': '1_Pooling/config.json', 'size': 200, 'sha256': '987f7a67a38fa564c849bb5d277c52ab9088a84368fc0be31a354125aebb12a0', 'url': 'https://huggingface.co/intfloat/multilingual-e5-small/resolve/614241f622f53c4eeff9890bdc4f31cfecc418b3/1_Pooling/config.json'}, {'path': 'config.json', 'size': 655, 'sha256': '69137736cab8b8903a07fe8afaafdda25aac55415a12a55d1bffa9f581abf959', 'url': 'https://huggingface.co/intfloat/multilingual-e5-small/resolve/614241f622f53c4eeff9890bdc4f31cfecc418b3/config.json'}, {'path': 'model.safetensors', 'size': 470641600, 'sha256': '1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477', 'url': 'https://huggingface.co/intfloat/multilingual-e5-small/resolve/614241f622f53c4eeff9890bdc4f31cfecc418b3/model.safetensors'}, {'path': 'modules.json', 'size': 387, 'sha256': 'c6e29747481e8b5dd2b58401966aeac910de39092f90cda9a704b1545f902b04', 'url': 'https://huggingface.co/intfloat/multilingual-e5-small/resolve/614241f622f53c4eeff9890bdc4f31cfecc418b3/modules.json'}, {'path': 'sentence_bert_config.json', 'size': 57, 'sha256': '948201d8329907aae938fa62f9ceeed53f5694dacc2b87b9f3b78b37ee986529', 'url': 'https://huggingface.co/intfloat/multilingual-e5-small/resolve/614241f622f53c4eeff9890bdc4f31cfecc418b3/sentence_bert_config.json'}, {'path': 'sentencepiece.bpe.model', 'size': 5069051, 'sha256': 'cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865', 'url': 'https://huggingface.co/intfloat/multilingual-e5-small/resolve/614241f622f53c4eeff9890bdc4f31cfecc418b3/sentencepiece.bpe.model'}, {'path': 'special_tokens_map.json', 'size': 167, 'sha256': 'd05497f1da52c5e09554c0cd874037a083e1dc1b9cfd48034d1c717f1afc07a7', 'url': 'https://huggingface.co/intfloat/multilingual-e5-small/resolve/614241f622f53c4eeff9890bdc4f31cfecc418b3/special_tokens_map.json'}, {'path': 'tokenizer.json', 'size': 17082730, 'sha256': '0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39', 'url': 'https://huggingface.co/intfloat/multilingual-e5-small/resolve/614241f622f53c4eeff9890bdc4f31cfecc418b3/tokenizer.json'}, {'path': 'tokenizer_config.json', 'size': 443, 'sha256': 'a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b', 'url': 'https://huggingface.co/intfloat/multilingual-e5-small/resolve/614241f622f53c4eeff9890bdc4f31cfecc418b3/tokenizer_config.json'}]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=Path('models/cache/multilingual-e5-small'))
    args = parser.parse_args()
    for item in FILES:
        acquire(item, args.destination)
        print('Verified', item['path'], flush=True)

if __name__ == '__main__':
    main()
