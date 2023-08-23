# -*- coding: utf-8 -*-
"""hauXLMR(train,dev,test).ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1LnnwwBXrV01y1CYG4Udi562BGgUzm4ze

#  <a>***Amharic_NER_Project Using XLM-RoBerta***

## <a>***Import the necessary libraries***
"""

# Commented out IPython magic to ensure Python compatibility.
# %%capture
# !pip install transformers
# !pip install SentencePiece

label_to_id = {"O":0, "B-ORG":1, "I-ORG":2, "B-PER":3, "I-PER":4, "B-LOC":5, "I-LOC":6, "B-DATE":7, "I-DATE":8}
id_to_label = {value: key for key, value in label_to_id.items()}

import numpy as np
import pandas as pd
import torch
from transformers import  XLMRobertaTokenizer, AutoTokenizer, AutoModel, XLMRobertaForTokenClassification, AdamW
from collections import defaultdict, namedtuple
from tqdm import tqdm
from torch.utils.data import TensorDataset, DataLoader
import sys
import re

from collections import defaultdict, namedtuple

ANY_SPACE = '<SPACE>'

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
torch.cuda.is_available()

"""## <a>***Load and Read the DataSets***"""

FILE_DIR_train = 'yor-200.txt'
FILE_DIR_dev   = 'dev.txt'
FILE_DIR_test  = 'test.txt'

df_Train = pd.read_csv(FILE_DIR_train, encoding="utf-8", delim_whitespace=True, header=None, skip_blank_lines=False)

df_Train.iloc[:,1].value_counts()

df_Val = pd.read_csv(FILE_DIR_dev, encoding="utf-8", delim_whitespace=True, header=None, skip_blank_lines=False)

df_Val.iloc[:,1].value_counts()

df_Test = pd.read_csv(FILE_DIR_test, encoding="utf-8", delim_whitespace=True, header=None, skip_blank_lines=False)

df_Test.iloc[:,1].value_counts()

"""## <a>***Preprocess and Tokenize the Data and Create DataLoader (Pytorch)***"""

XLMTokenizer = XLMRobertaTokenizer.from_pretrained('Davlan/afro-xlmr-base')
XLMModel     = XLMRobertaForTokenClassification.from_pretrained('Davlan/afro-xlmr-base',num_labels=9)

def preprocess_data(PATH_DATASET, tokenizer, max_seq_length=512):
    data = pd.read_csv(PATH_DATASET, encoding="utf-8", delim_whitespace=True, header=None, skip_blank_lines=False)
    Instance = namedtuple("Instance", ["tokenized_text", "input_ids", "input_mask", "labels", "label_ids"])
    pad_token_label_id = torch.nn.CrossEntropyLoss().ignore_index
    dataset = []
    text = []
    labels = []
    jj=0
    for w, l in zip(data[0], data[1]):
        jj+=1
        # print(jj)
        # print(w,l)

        if str(w) == "nan" and str(l) == "nan":
            tokens = []
            label_ids = []

            for i in range(len(text)):
              word_tokens = tokenizer.tokenize(text[i])
              tokens.extend(word_tokens)
              # Use the real label id for the first token of the word, and padding ids for the remaining tokens
              label_ids.extend([label_to_id[labels[i]]] + [pad_token_label_id] * (len(word_tokens) - 1))

            if len(tokens) > max_seq_length - 2:
              tokens = tokens[: (max_seq_length - 2)]
              label_ids = label_ids[: (max_seq_length - 2)]

            tokens += ['[SEP]']
            label_ids += [pad_token_label_id]

            tokens = ['[CLS]'] + tokens
            label_ids = [pad_token_label_id] + label_ids

            input_ids = tokenizer.convert_tokens_to_ids(tokens)

            input_mask = [1] * len(input_ids)

            padding_length = max_seq_length - len(input_ids)

            input_ids = ([0] * padding_length) + input_ids
            input_mask = ([0] * padding_length) + input_mask
            label_ids = ([pad_token_label_id] * padding_length) + label_ids

            dataset.append(Instance(tokens, input_ids,
                            input_mask, labels, label_ids))

            text = []
            labels = []
            continue

        elif (str(w) == "nan" and str(l) != "nan") or str(w) != "nan" and str(l) == "nan":
          print(jj)
          continue
        text.append(str(w))
        labels.append(str(l))


    return dataset

def transform_to_tensors(dataset):
    tensors_input_ids = []
    tensors_input_mask = []
    tensors_label_ids = []
    for i in dataset:
        tensors_input_ids.append(i.input_ids)
        tensors_input_mask.append(i.input_mask)
        tensors_label_ids.append(i.label_ids)

    return torch.tensor(tensors_input_ids), torch.tensor(tensors_input_mask), torch.tensor(tensors_label_ids)

train_Dataset = preprocess_data(FILE_DIR_train, XLMTokenizer, max_seq_length=512)
val_Dataset   = preprocess_data(FILE_DIR_dev, XLMTokenizer, max_seq_length=512)
test_Dataset  = preprocess_data(FILE_DIR_test, XLMTokenizer, max_seq_length=512)

len(train_Dataset), len(val_Dataset), len(test_Dataset)

train_tensors_input_ids, train_tensors_input_mask, train_tensors_label_ids = transform_to_tensors(train_Dataset)
val_tensors_input_ids, val_tensors_input_mask, val_tensors_label_ids       = transform_to_tensors(val_Dataset)
test_tensors_input_ids, test_tensors_input_mask, test_tensors_label_ids    = transform_to_tensors(test_Dataset)

train_tensor_dataset = TensorDataset(train_tensors_input_ids, train_tensors_input_mask, train_tensors_label_ids)
val_tensor_dataset   = TensorDataset(val_tensors_input_ids, val_tensors_input_mask, val_tensors_label_ids)
test_tensor_dataset  = TensorDataset(test_tensors_input_ids, test_tensors_input_mask, test_tensors_label_ids)

train_dataloader = DataLoader(train_tensor_dataset, batch_size=1)
val_dataloader   = DataLoader(val_tensor_dataset, batch_size=1)
test_dataloader  = DataLoader(test_tensor_dataset, batch_size=1)

"""## <a>***Training and Evaluation***

### <a>***Required Functions***
"""

def train(model, optimizer, train_dataloader, val_dataloader, dataset_val, accumulation_steps=32, epochs=1, device="cpu"):
    model.to(device)
    best_f1_score = 0
    best_model = None
    loss_fct = torch.nn.CrossEntropyLoss()

    history_dict={"train_loss":    [],"val_loss":     [],
                  "DATE_f1_score": [],"LOC_f1_score": [],"ORG_f1_score": [],"PER_f1_score": [],"Model_f1_score": [],
                  "DATE_precision":[],"LOC_precision":[],"ORG_precision":[],"PER_precision":[],"Model_precision":[],
                  "DATE_recall":   [],"LOC_recall":   [],"ORG_recall":   [],"PER_recall":   [],"Model_recall":   []}

    for epoch in range(epochs):
        training_loss = 0.0
        val_loss = 0.0

        model.train()
        cnt_step = 0
        for batch in tqdm(train_dataloader):

            input_ids, input_mask, label_ids = batch
            input_ids = input_ids.to(device)
            input_mask = input_mask.to(device)
            label_ids = label_ids.to(device)

            logits = model(input_ids=input_ids, attention_mask=input_mask, labels=label_ids)[1]

            active_loss = input_mask.view(-1) == 1
            active_logits = logits.view(-1, 9)
            active_labels = torch.where(active_loss, label_ids.view(-1), torch.tensor(loss_fct.ignore_index).type_as(label_ids))
            # print(active_logits.shape, active_labels.shape)

            loss = loss_fct(active_logits, active_labels)

            training_loss += loss.data.item()

            loss = loss / accumulation_steps
            loss.backward()

            if (cnt_step + 1) % accumulation_steps == 0:
                optimizer.step()
                optimizer.zero_grad()
            cnt_step += 1

        training_loss /= cnt_step

        model.eval()
        with torch.no_grad():
            for batch in tqdm(val_dataloader):
                input_ids, input_mask, label_ids = batch
                input_ids = input_ids.to(device)
                input_mask = input_mask.to(device)
                label_ids = label_ids.to(device)

                logits = model(input_ids=input_ids, attention_mask=input_mask, labels=label_ids)[1]

                active_loss = input_mask.view(-1) == 1
                active_logits = logits.view(-1, 9)
                active_labels = torch.where(active_loss, label_ids.view(-1), torch.tensor(loss_fct.ignore_index).type_as(label_ids))

                loss = loss_fct(active_logits, active_labels)

                val_loss += loss.data.item()

            val_loss /= len(val_dataloader)

            print("epoch {}: training loss {}, val loss {}".format(epoch, training_loss, val_loss))
            history_dict["train_loss"].append(training_loss)
            history_dict["val_loss"].append(val_loss)


        f1_score_arr, prec_score_arr, rec_score_arr, _ = evaluatemodel(model, "val.txt", dataset_val, val_dataloader)

        history_dict["DATE_f1_score"].append(f1_score_arr[0])
        history_dict["LOC_f1_score"].append(f1_score_arr[1])
        history_dict["ORG_f1_score"].append(f1_score_arr[2])
        history_dict["PER_f1_score"].append(f1_score_arr[3])
        history_dict["Model_f1_score"].append(f1_score_arr[4])

        history_dict["DATE_precision"].append(prec_score_arr[0])
        history_dict["LOC_precision"].append(prec_score_arr[1])
        history_dict["ORG_precision"].append(prec_score_arr[2])
        history_dict["PER_precision"].append(prec_score_arr[3])
        history_dict["Model_precision"].append(prec_score_arr[4])

        history_dict["DATE_recall"].append(rec_score_arr[0])
        history_dict["LOC_recall"].append(rec_score_arr[1])
        history_dict["ORG_recall"].append(rec_score_arr[2])
        history_dict["PER_recall"].append(rec_score_arr[3])
        history_dict["Model_recall"].append(rec_score_arr[4])

        if f1_score_arr[4] > best_f1_score:
            best_f1_score = f1_score_arr[4]
            best_model = model
            print("We have a better model with an F1 Score: {}".format(best_f1_score))

    return best_model,history_dict


class FormatError(Exception):
    pass

Metrics = namedtuple('Metrics', 'tp fp fn prec rec fscore')

class EvalCounts(object):
    def __init__(self):
        self.correct_chunk = 0    # number of correctly identified chunks
        self.correct_tags = 0     # number of correct chunk tags
        self.found_correct = 0    # number of chunks in corpus
        self.found_guessed = 0    # number of identified chunks
        self.token_counter = 0    # token counter (ignores sentence breaks)

        # counts by type
        self.t_correct_chunk = defaultdict(int)
        self.t_found_correct = defaultdict(int)
        self.t_found_guessed = defaultdict(int)

def parse_args(argv):
    import argparse
    parser = argparse.ArgumentParser(
        description='evaluate tagging results using CoNLL criteria',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    arg = parser.add_argument
    arg('-b', '--boundary', metavar='STR', default='-X-',
        help='sentence boundary')
    arg('-d', '--delimiter', metavar='CHAR', default=ANY_SPACE,
        help='character delimiting items in input')
    arg('-o', '--otag', metavar='CHAR', default='O',
        help='alternative outside tag')
    arg('file', nargs='?', default=None)
    return parser.parse_args(argv)

def parse_tag(t):
    m = re.match(r'^([^-]*)-(.*)$', t)
    return m.groups() if m else (t, '')

def evaluate(iterable, options=None):
    if options is None:
        options = parse_args([])    # use defaults

    counts = EvalCounts()
    num_features = None       # number of features per line
    in_correct = False        # currently processed chunks is correct until now
    last_correct = 'O'        # previous chunk tag in corpus
    last_correct_type = ''    # type of previously identified chunk tag
    last_guessed = 'O'        # previously identified chunk tag
    last_guessed_type = ''    # type of previous chunk tag in corpus

    for line in iterable:
        line = line.rstrip('\r\n')

        if options.delimiter == ANY_SPACE:
            features = line.split()
        else:
            features = line.split(options.delimiter)

        if num_features is None:
            num_features = len(features)
        elif num_features != len(features) and len(features) != 0:
            raise FormatError('unexpected number of features: %d (%d)' %
                              (len(features), num_features))

        if len(features) == 0 or features[0] == options.boundary:
            features = [options.boundary, 'O', 'O']
        if len(features) < 3:
            raise FormatError('unexpected number of features in line %s' % line)

        guessed, guessed_type = parse_tag(features.pop())
        correct, correct_type = parse_tag(features.pop())
        first_item = features.pop(0)

        if first_item == options.boundary:
            guessed = 'O'

        end_correct = end_of_chunk(last_correct, correct,
                                   last_correct_type, correct_type)
        end_guessed = end_of_chunk(last_guessed, guessed,
                                   last_guessed_type, guessed_type)
        start_correct = start_of_chunk(last_correct, correct,
                                       last_correct_type, correct_type)
        start_guessed = start_of_chunk(last_guessed, guessed,
                                       last_guessed_type, guessed_type)

        if in_correct:
            if (end_correct and end_guessed and
                last_guessed_type == last_correct_type):
                in_correct = False
                counts.correct_chunk += 1
                counts.t_correct_chunk[last_correct_type] += 1
            elif (end_correct != end_guessed or guessed_type != correct_type):
                in_correct = False

        if start_correct and start_guessed and guessed_type == correct_type:
            in_correct = True

        if start_correct:
            counts.found_correct += 1
            counts.t_found_correct[correct_type] += 1
        if start_guessed:
            counts.found_guessed += 1
            counts.t_found_guessed[guessed_type] += 1
        if first_item != options.boundary:
            if correct == guessed and guessed_type == correct_type:
                counts.correct_tags += 1
            counts.token_counter += 1

        last_guessed = guessed
        last_correct = correct
        last_guessed_type = guessed_type
        last_correct_type = correct_type

    if in_correct:
        counts.correct_chunk += 1
        counts.t_correct_chunk[last_correct_type] += 1

    return counts

def uniq(iterable):
  seen = set()
  return [i for i in iterable if not (i in seen or seen.add(i))]

def calculate_metrics(correct, guessed, total):
    tp, fp, fn = correct, guessed-correct, total-correct
    p = 0 if tp + fp == 0 else 1.*tp / (tp + fp)
    r = 0 if tp + fn == 0 else 1.*tp / (tp + fn)
    f = 0 if p + r == 0 else 2 * p * r / (p + r)
    return Metrics(tp, fp, fn, p, r, f)

def metrics(counts):
    c = counts
    overall = calculate_metrics(
        c.correct_chunk, c.found_guessed, c.found_correct
    )
    by_type = {}
    # print(c.t_found_guessed.keys())
    # print(uniq(c.t_found_correct.keys() + c.t_found_guessed.keys()))
    # dict_keys = c.t_found_correct.copy()
    # dict_keys.update(c.t_found_guessed.keys)
    list_keys = list(c.t_found_correct.keys())
    list_keys += list(c.t_found_guessed.keys())

    for t in set(list_keys):  # uniq(c.t_found_correct.keys() + c.t_found_guessed.keys()):
        by_type[t] = calculate_metrics(
            c.t_correct_chunk[t], c.t_found_guessed[t], c.t_found_correct[t]
        )
    return overall, by_type

def report(counts, out=None):
    if out is None:
        out = sys.stdout

    overall, by_type = metrics(counts)

    c = counts
    out.write('processed %d tokens with %d phrases; ' %
              (c.token_counter, c.found_correct))
    out.write('found: %d phrases; correct: %d.\n' %
              (c.found_guessed, c.correct_chunk))

    f1_results_arr = []
    prec_results_arr = []
    rec_results_arr = []
    if c.token_counter > 0:
        out.write('accuracy: %6.2f%%; ' %
                  (100.*c.correct_tags/c.token_counter))
        out.write('precision: %6.2f%%; ' % (100.*overall.prec))
        out.write('recall: %6.2f%%; ' % (100.*overall.rec))
        out.write('FB1: %6.2f\n' % (100.*overall.fscore))

    for i, m in sorted(by_type.items()):
        out.write('%17s: ' % i)
        out.write('precision: %6.2f%%; ' % (100.*m.prec))
        out.write('recall: %6.2f%%; ' % (100.*m.rec))
        out.write('FB1: %6.2f  %d\n' % (100.*m.fscore, c.t_found_guessed[i]))
        f1_results_arr.append(100.*m.fscore)
        prec_results_arr.append(100.*m.prec)
        rec_results_arr.append(100.*m.rec)

    f1_results_arr.append(100.*overall.fscore)
    prec_results_arr.append(100.*overall.prec)
    rec_results_arr.append(100.*overall.rec)

    return overall.fscore, f1_results_arr,prec_results_arr,rec_results_arr

def end_of_chunk(prev_tag, tag, prev_type, type_):
    # check if a chunk ended between the previous and current word
    # arguments: previous and current chunk tags, previous and current types
    chunk_end = False

    if prev_tag == 'E': chunk_end = True
    if prev_tag == 'S': chunk_end = True

    if prev_tag == 'B' and tag == 'B': chunk_end = True
    if prev_tag == 'B' and tag == 'S': chunk_end = True
    if prev_tag == 'B' and tag == 'O': chunk_end = True
    if prev_tag == 'I' and tag == 'B': chunk_end = True
    if prev_tag == 'I' and tag == 'S': chunk_end = True
    if prev_tag == 'I' and tag == 'O': chunk_end = True

    if prev_tag != 'O' and prev_tag != '.' and prev_type != type_:
        chunk_end = True

    # these chunks are assumed to have length 1
    if prev_tag == ']': chunk_end = True
    if prev_tag == '[': chunk_end = True

    return chunk_end

def start_of_chunk(prev_tag, tag, prev_type, type_):
    # check if a chunk started between the previous and current word
    # arguments: previous and current chunk tags, previous and current types
    chunk_start = False

    if tag == 'B': chunk_start = True
    if tag == 'S': chunk_start = True

    if prev_tag == 'E' and tag == 'E': chunk_start = True
    if prev_tag == 'E' and tag == 'I': chunk_start = True
    if prev_tag == 'S' and tag == 'E': chunk_start = True
    if prev_tag == 'S' and tag == 'I': chunk_start = True
    if prev_tag == 'O' and tag == 'E': chunk_start = True
    if prev_tag == 'O' and tag == 'I': chunk_start = True

    if tag != 'O' and tag != '.' and prev_type != type_:
        chunk_start = True

    # these chunks are assumed to have length 1
    if tag == '[': chunk_start = True
    if tag == ']': chunk_start = True

    return chunk_start

def eval_f1score(file_):

    with open(file_) as f:
        counts = evaluate(f)
    f1score, fscore_arr, prec_arr, rec_arr = report(counts)
    print("fscore_arr",fscore_arr)
    print("prec_arr",prec_arr)
    print("rec_arr",rec_arr)
    return f1score, fscore_arr, prec_arr, rec_arr


def evaluatemodel(model, filename, dataset, dataloader):
    global id_to_label
    model.eval()
    f1_score = 0

    with torch.no_grad():
        fw =  open("{}".format(filename), "w")
        cnt = 0
        for batch in tqdm(dataloader):
            input_ids, input_mask, _ = batch
            input_ids = input_ids.to(device)
            input_mask = input_mask.to(device)
            output = model(input_ids=input_ids, attention_mask=input_mask)[0]
            mask = torch.tensor(np.array(dataset[cnt].label_ids) != -100)
            mask_ = mask.unsqueeze(-1).expand(output.size()).to(device)
            output = torch.masked_select(output, mask_.bool()).view(1,-1,9)


            text = XLMTokenizer.decode(XLMTokenizer.convert_tokens_to_ids(dataset[cnt].tokenized_text)[1:-1]).split(' ')
            length = len(text)
            for w in range(length):
                word = text[w]

                true_label = dataset[cnt].labels[w]

                pred_label = id_to_label[torch.argmax(output.squeeze(0)[w]).item()]
                fw.write("{} {} {}\n".format(word, true_label, pred_label))
            fw.write("\n")
            cnt += 1
        fw.close()

        overall_Score, f1_score_arr, prec_score_arr, rec_score_arr = eval_f1score("{}".format(filename))


    return f1_score_arr,prec_score_arr, rec_score_arr, overall_Score


for param in XLMModel.parameters():
  param.requires_grad = True
params_to_update = [param for param in XLMModel.parameters() if param.requires_grad != False]

optimizer = AdamW(params_to_update, lr=2e-5)

"""### <a>***Training the Model***"""

trained_model,history = train(XLMModel, optimizer, train_dataloader, val_dataloader, val_Dataset, epochs=23, device=device)

"""### <a>***History Plots***"""

from IPython.display import Image, display
import matplotlib.pyplot as plt
import plotly.graph_objects as go
import seaborn as sns

plt.figure(figsize=(18,8))
plt.style.use("ggplot")
title = "Training and Validation Loss "
plt.suptitle(title, fontsize=18)

plt.plot(history['train_loss'], label='Training Loss')
plt.plot(history['val_loss'], label='Validation Loss')
plt.legend()
plt.xlabel('Number of Epochs', fontsize=16)
plt.ylabel('Loss', fontsize=16)

plt.show()

plt.figure(figsize=(18,8))
plt.style.use("ggplot")
title = "NER F1 Scores"
plt.suptitle(title, fontsize=18)

plt.plot(history['DATE_f1_score'], label='DATE f1_score')
plt.plot(history['LOC_f1_score'], label='LOC f1_score')
plt.plot(history['ORG_f1_score'], label='ORG f1_score')
plt.plot(history['PER_f1_score'], label='PER f1_score')
plt.plot(history['Model_f1_score'], label='Model f1_score')
plt.legend()
plt.xlabel('Number of Epochs', fontsize=16)
plt.ylabel('F1 Score', fontsize=16)

plt.show()

plt.figure(figsize=(18,8))
plt.style.use("ggplot")
title = "NER Precision"
plt.suptitle(title, fontsize=18)

plt.plot(history['DATE_precision'], label='DATE Precision')
plt.plot(history['LOC_precision'], label='LOC Precision')
plt.plot(history['ORG_precision'], label='ORG Precision')
plt.plot(history['PER_precision'], label='PER Precision')
plt.plot(history['Model_precision'], label='Model Precision')
plt.legend()
plt.xlabel('Number of Epochs', fontsize=16)
plt.ylabel('Precision', fontsize=16)

plt.show()

plt.figure(figsize=(18,8))
plt.style.use("ggplot")
title = "NER Recall"
plt.suptitle(title, fontsize=18)

plt.plot(history['DATE_recall'], label='DATE Recall')
plt.plot(history['LOC_recall'], label='LOC Recall')
plt.plot(history['ORG_recall'], label='ORG Recall')
plt.plot(history['PER_recall'], label='PER Recall')
plt.plot(history['Model_recall'], label='Model Recall')
plt.legend()
plt.xlabel('Number of Epochs', fontsize=16)
plt.ylabel('Recall', fontsize=16)

plt.show()

"""### <a>***Evaluate the Model on the Test Data***"""

evaluatemodel(trained_model,'test.txt',test_Dataset,test_dataloader)