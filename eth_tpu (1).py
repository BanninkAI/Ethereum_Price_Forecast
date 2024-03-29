# -*- coding: utf-8 -*-
"""Eth_TPU.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1yB_xFluRsyuZi3FRWF2wYqokkrK7hqkm
"""

import tensorflow as tf

import os
import tensorflow_datasets as tfds

tpu = tf.distribute.cluster_resolver.TPUClusterResolver()
print('Running on TPU ', tpu.cluster_spec().as_dict()['worker'])

tf.config.experimental_connect_to_cluster(tpu)
tf.tpu.experimental.initialize_tpu_system(tpu)

strategy = tf.distribute.experimental.TPUStrategy(tpu)
print("REPLICAS: ", strategy.num_replicas_in_sync)

from typing import List
#modify data
import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler
from sklearn.preprocessing import StandardScaler
import math
import random

def retrieve_data(filename):
  # Remove redundant features if they are found
  data = pd.read_csv(filename, usecols=['Open', 'High','Low', 'Close', 'Volume'])
  # Variables: ['Open', 'High','Low', 'Close', 'Volume']
  return data.to_numpy()

def scaleAndFilterData(data, testsize=0.13):
  # Split the train and test data, not at random, only last section for test set such that
  # the model has not seen already seen any of the data it is tested on (more realistic scenario)
  split_index = math.floor((1-testsize)*len(data))
  train_data = data[:split_index]
  test_data = data[split_index:]
  #perform standardization (not norm) to scale data, in this case i think its better, with minmaxscaling prices like 80$ will be squashed to almost zero
  #when we have also prices of 3000 or something like that, scale train and test data separately
  # Perform minmax-scaling (separately for train and test data)
  train_scaler = StandardScaler()
  scaled_train = np.array(train_scaler.fit_transform(train_data))
  scaled_test = np.array(train_scaler.transform(test_data))
  return train_scaler, scaled_train, scaled_test

def shuffleLists(eth_train, btc_train, y, decoder_data):
  "shuffle the data at random, so that we (hopefully) learn better, otherwise, within a batch, all patters are really similar, just forcing it to learn a certain pattern"
  "for each batch, however, now a batch consists of random samples over time, forcing the model to (hopefully) learn a global pattern from a batch"
  "instead of forcing a (potential) local pattern"
  combined = list(zip(eth_train,btc_train,y, decoder_data))
  random.shuffle(combined)
  eth_train,btc_brain,y, decoder_data = zip(*combined)
  y = np.stack(y)
  y = np.reshape(y,(y.shape[0],y.shape[1]))
  decoder_data = np.stack(decoder_data)
  decoder_data = np.reshape(decoder_data,(decoder_data.shape[0],decoder_data.shape[1],2))
  return (np.stack(eth_train), np.stack(btc_train), y, decoder_data)

def createTimeEmbeddingsInput( data_slice, sequence_length, week_length):
  time_vector_days =  np.linspace(0, 1, sequence_length)
  time_vector_week = np.linspace(0,1,week_length)
  complete_time_embedding = np.concatenate((time_vector_week, time_vector_days))
  reshape = np.reshape(complete_time_embedding,(len(complete_time_embedding),1))
  return reshape

def createTimeEmbeddingsOutput(data_slice, sequence_length, week_length):
  target_embedding = np.linspace(0,1,7)
  reshape = np.reshape(target_embedding, (len(target_embedding),1))
  return reshape

def prepareTrainDataX(data_daily_og, data_weekly_og,sequence_length, week_length ):
  #we need want to start at same data of weeks and daily and then 8 weeks prior, so thats 56 days already discarded
  #and we need to start on same date, first date in common is 11-13, so we start from there, that means already 1 input of week discarded and first 4 days discarded,
  #which means 60 days and 1 week discarded from the dataset
  #then discard last 7 entries from daily and 1 from weekly as we predict 7 days ahead with model
  data_daily = np.array(data_daily_og[3:-2]) #skip first 4 entries and last 2 to line up dates with the weekly
  data_weekly=np.array(data_weekly_og[1:-2]) #same here
  data_daily = data_daily[week_length*6+3:-7]
  all_sequences = []
  for i in range(data_daily.shape[0]):
    slice_daily = data_daily[i:i+sequence_length]
    if slice_daily.shape[0]<sequence_length:
      break
    weekly_index = i//7
    slice_weekly = data_weekly[weekly_index:weekly_index+8]
    combined_data = np.concatenate((slice_weekly, slice_daily))
    time_embedding_input = createTimeEmbeddingsInput(data_slice= combined_data, sequence_length= sequence_length, week_length= week_length)
    final = np.concatenate((time_embedding_input,combined_data), axis=-1)
    if final.shape[0]<sequence_length+week_length:
      break
    all_sequences.append(final)
  return all_sequences



def prepareTargetDataY(data_daily_og, sequence_length, week_length, train=True):
  #we do the original modification of the train data, getting rid of the fist 3 entries
  #then we get rid of the first 56 as with train, as this was required to have the 8 week historic price action
  #then we get rid of 28, days as these are used for the first set of training data, so no prediction is made using these dayts
  #so in total, get rid of 84 entries then, first entry is a target value, we predict 7 values ahead of the close price (3 index in array)
  data = np.array(data_daily_og[3:-2,3]) #skip first 4 entries and last 2 to line up dates with the weekly
  data = data[week_length*6 + sequence_length+3:]
  sequence_y = []
  for i in range(len(data)-6):
    forecast_target = data[i:i+7]
    forecast_target = np.reshape(forecast_target,(len(forecast_target),1))
    sequence_y.append(forecast_target)
  return sequence_y

def prepareDecoderData(data_daily_og, sequence_length, week_length, train=True):
  #we do the original modification of the train data, getting rid of the fist 3 entries
  #then we get rid of the first 56 as with train, as this was required to have the 8 week historic price action
  #then we get rid of 28, days as these are used for the first set of training data, so no prediction is made using these dayts
  #so in total, get rid of 84 entries then, first entry is a target value, we predict 7 values ahead of the close price (3 index in array)
  if train:
    data = np.array(data_daily_og[3:-2,3]) #skip first 4 entries and last 2 to line up dates with the weekly
    data = data[week_length*6 + sequence_length+2:]
  sequence_y = []
  for i in range(len(data)-7):
    forecast_target = data[i:i+7]
    timevec = createTimeEmbeddingsOutput(forecast_target,sequence_length, week_length)
    forecast_target = np.reshape(forecast_target,(len(forecast_target),1))
    final_slice = np.concatenate((timevec,forecast_target), axis=-1)
    sequence_y.append(final_slice)
  return sequence_y


sequence_length = 42
week_length = 8

#loading in all data and retaining the standardscalers, data for all dataset: Nov 09, 2017 - Jan 10, 2024
eth_daily_scaled_train, eth_daily_train_data, eth_daily_test_data = scaleAndFilterData(retrieve_data("ETH-USD - daily.csv"))
eth_weekly_scaled_train, eth_weekly_train_data, eth_weekly_test_data = scaleAndFilterData(retrieve_data("ETH-USD - weekly.csv"))
btc_daily_scaled_train, btc_daily_train_data, btc_daily_test_data = scaleAndFilterData(retrieve_data("BTC-USD - daily.csv"))
btc_weekly_scaled_train, btc_weekly_train_data, btc_weekly_test_data = scaleAndFilterData(retrieve_data("BTC-USD - weekly.csv"))
#transform the data such that we create a 3d dataset such that: (inputs, sequence-lenght, variables) -> take sequence length of 28 days and 4 weeks and 8 weeks prior -> sequence length is 40
eth_train_data = prepareTrainDataX(eth_daily_train_data, eth_weekly_train_data, sequence_length, week_length)
btc_train_data = prepareTrainDataX(btc_daily_train_data,btc_weekly_train_data, sequence_length, week_length)
target_eth=prepareTargetDataY(eth_daily_train_data, sequence_length, week_length)
decoder_data =prepareDecoderData(eth_daily_train_data, sequence_length, week_length)
eth_train_data, btc_train_data, target_eth, decoder_data = shuffleLists(eth_train_data,btc_train_data, target_eth,decoder_data )
#code for data is handchecked and correct check if for yyourself by printing the last and first entries of targetY and trainX and look it up in the excel files,
#with the week and
complete_data = (eth_train_data,btc_train_data, decoder_data )
print(eth_train_data.shape)
print(btc_train_data.shape)
print(decoder_data.shape)
print(target_eth.shape)

#test data creation
def prepareTestDataX(data_daily_og, data_weekly_og,sequence_length, week_length ):
  #we need want to start at same data of weeks and daily and then 8 weeks prior, so thats 56 days already discarded
  #and we need to start on same date, first date in common is 11-13, so we start from there, that means already 1 input of week discarded and first 4 days discarded,
  #which means 60 days and 1 week discarded from the dataset
  #then discard last 7 entries from daily and 1 from weekly as we predict 7 days ahead with model
  data_daily_test = np.array(data_daily_og[4:]) #skip first 4 entries and last 2 to line up dates with the weekly
  data_weekly_test=np.array(data_weekly_og) #same here
  data_daily_test = data_daily_test[week_length*6+2:-7]
  all_sequences = []
  for i in range(data_daily_test.shape[0]):
    slice_daily = data_daily_test[i:i+sequence_length]
    if slice_daily.shape[0]<sequence_length:
      break
    weekly_index = i//7
    slice_weekly = data_weekly_test[weekly_index:weekly_index+8]
    combined_data = np.concatenate((slice_weekly, slice_daily))
    time_embedding_input = createTimeEmbeddingsInput(data_slice= combined_data, sequence_length= sequence_length, week_length= week_length)
    final = np.concatenate((time_embedding_input,combined_data), axis=-1)
    if final.shape[0]<sequence_length+week_length:
      break
    all_sequences.append(final)
  return all_sequences



def prepareTargetDataYTest(data_daily_og, sequence_length, week_length):
  #we do the original modification of the train data, getting rid of the fist 3 entries
  #then we get rid of the first 56 as with train, as this was required to have the 8 week historic price action
  #then we get rid of 28, days as these are used for the first set of training data, so no prediction is made using these dayts
  #so in total, get rid of 84 entries then, first entry is a target value, we predict 7 values ahead of the close price (3 index in array)
  data = np.array(data_daily_og[4:,3]) #skip first 4 entries and last 2 to line up dates with the weekly
  data = data[week_length*6 + sequence_length+2:]
  sequence_y = []
  for i in range(len(data)-6):
    forecast_target = data[i:i+7]
    forecast_target = np.reshape(forecast_target,(len(forecast_target),1))
    sequence_y.append(forecast_target)
  return sequence_y

def prepareDecoderDataTest(data_daily_og, sequence_length, week_length):
  #we do the original modification of the train data, getting rid of the fist 3 entries
  #then we get rid of the first 56 as with train, as this was required to have the 8 week historic price action
  #then we get rid of 28, days as these are used for the first set of training data, so no prediction is made using these dayts
  #so in total, get rid of 84 entries then, first entry is a target value, we predict 7 values ahead of the close price (3 index in array)

  data = np.array(data_daily_og[4:,3]) #skip first 4 entries and last 2 to line up dates with the weekly
  data = data[week_length*6 + sequence_length+1:]
  sequence_y = []
  for i in range(len(data)-7):
    #now only the first as in the test set, to make it completely realistic, we will not know the next prices for the coming days
    forecast_target = np.array(data[i])
    #timevec = createTimeEmbeddingsOutputSpecial(forecast_target,sequence_length, week_length)
    forecast_target = np.reshape(forecast_target,(1,1))
    #final_slice = np.concatenate((timevec,forecast_target), axis=-1)
    sequence_y.append(forecast_target)
  return sequence_y


def stackData(eth_test, btc_test, y_test, decoder_data_test):
  y_test = np.stack(y_test)
  y_test = np.reshape(y_test,(y_test.shape[0],y_test.shape[1]))
  decoder_data_test = np.stack(decoder_data_test)
  decoder_data_test = np.reshape(decoder_data_test,(decoder_data_test.shape[0],decoder_data_test.shape[1],1))
  return (np.stack(eth_test), np.stack(btc_test), y_test, decoder_data_test)

eth_test_data = prepareTestDataX(eth_daily_test_data, eth_weekly_test_data, sequence_length, week_length)
btc_test_data = prepareTestDataX(btc_daily_test_data,btc_weekly_test_data, sequence_length, week_length)
target_eth_test=prepareTargetDataYTest(eth_daily_test_data, sequence_length, week_length)
decoder_data_test =prepareDecoderDataTest(eth_daily_test_data, sequence_length, week_length)
eth_test_data, btc_test_data, target_eth_test, decoder_data_test = stackData(eth_test_data,btc_test_data, target_eth_test,decoder_data_test )
print(eth_test_data.shape)
print(btc_test_data.shape)
print(decoder_data_test.shape)
print(target_eth_test.shape)
complete_test_data = (eth_test_data, btc_test_data,decoder_data_test)
compete_test_data_batch = (eth_test_data, btc_test_data,decoder_data_test, target_eth_test)

#time2vec layer
import tensorflow as tf
from keras.layers import Layer
from tensorflow import keras
from keras.layers import concatenate

class Time2Vec(Layer):

    def __init__(self, k=4, **kwargs):
        self.k = k
        super(Time2Vec, self).__init__(**kwargs)

    def build(self, input_shape):
        #times the input, so amount of rows of w must be equal to amount of colums of input, we multiple input * weights instead of the opposite (used in paper)
      self.w = self.add_weight(shape=(input_shape[-1], self.k), initializer='uniform',trainable=True,regularizer=L2(0.001))#weights if i>0
      self.fi = self.add_weight(shape=(input_shape[1],self.k),initializer='uniform',trainable=True, regularizer=L2(0.001))#weights if i>0

      self.w0 = self.add_weight(shape=(input_shape[-1],1),initializer='uniform', trainable=True,regularizer=L2(0.001)) #weights for i=0
      self.fi0 = self.add_weight(shape=(input_shape[1],1),initializer='uniform', trainable=True,regularizer=L2(0.001)) #weights for i=0
      super(Time2Vec, self).build(input_shape)

    def call(self, inputs):
      input_shape = tf.shape(inputs)
      first_entry = tf.matmul(inputs,self.w0) +self.fi0[:input_shape[1]]
      rest_of_time_vector = tf.matmul(inputs,self.w) + self.fi[:input_shape[1]]
      output = tf.math.sin(rest_of_time_vector)
      return_value = concatenate([first_entry,output], -1)
      #also flatten output? but what is the point then of the timedistributed layer
      return return_value

    def get_config(self):
      config = super().get_config().copy()
      config.update({
        'k': self.k
      })
      return config

#creating the encoder part
from keras.layers import MultiHeadAttention
from keras.layers import LayerNormalization
from keras.layers import TimeDistributed
from keras.layers import LeakyReLU
from keras.layers import Dense
from keras.regularizers import L1
from keras.regularizers import L2


class Encoder(Layer):

    def __init__(self, dropout=0.2, amount_of_heads=8, size_of_head= 128,number_ff_layers=3,output_dim =10,**kwargs):
        super(Encoder,self).__init__(**kwargs)
        self.dropout = dropout
        self.amount_of_heads= amount_of_heads
        self.size_of_head = size_of_head
        self.output_dim = output_dim
        self.number_ff_layers = number_ff_layers

    def build(self, input_shape):
        self.multi_Attention = MultiHeadAttention(key_dim=self.size_of_head, num_heads=self.amount_of_heads, value_dim= self.size_of_head, dropout=self.dropout, attention_axes= (1,2), kernel_regularizer=L2(0.0005))
        self.norm_att = LayerNormalization()
        self.ff_layers =[]
        for i in range(self.number_ff_layers):
          self.ff_layers.append(Dense((10*self.number_ff_layers)/(i+1), use_bias=True,kernel_regularizer=L2(0.001)))
          self.ff_layers.append(LeakyReLU(alpha=0.3))
        self.norm_ff = LayerNormalization(axis=-1)
        super(Encoder, self).build(input_shape)

    def call(self, inputs, training = None):
        forward = self.multi_Attention(inputs, inputs, training = training)
        normalization_output = self.norm_att(inputs+forward)
        forward = normalization_output
        for ff_layer in self.ff_layers:
          forward = TimeDistributed(ff_layer)(forward)
        forward = self.norm_ff(forward+normalization_output)
        return forward

    def get_config(self):
      config = super().get_config().copy()
      config.update({
        'dropout': self.dropout,
        'amount_of_heads': self.amount_of_heads,
        'size_of_head': self.size_of_head,
        'output_dim' : self.output_dim,
        'number_ff_layers' : self.number_ff_layers,
      })
      return config

#decoder
class Decoder(Layer):

    def __init__(self, dropout=0.2, amount_of_heads=8, size_of_head= 128 , output_dim=10,amount_of_heads_masked=4, size_of_head_masked=32 ,dim_list=None,**kwargs ):
      super(Decoder,self).__init__(**kwargs)
      self.dropout = dropout
      self.amount_of_heads= amount_of_heads
      self.size_of_head = size_of_head
      self.output_dim = output_dim
      self.size_of_head_masked= size_of_head_masked
      self.amount_of_heads_masked = amount_of_heads_masked
      self.dim_list = dim_list

    def build(self, input_shape):
      self.masked_multi_attention = MultiHeadAttention(key_dim=self.size_of_head_masked ,num_heads=self.amount_of_heads_masked, value_dim= self.size_of_head_masked, dropout=self.dropout, use_bias=True,kernel_regularizer=L2(0.0005))
      self.multi_Attention = MultiHeadAttention(key_dim=self.size_of_head, num_heads=self.amount_of_heads, value_dim= self.size_of_head, dropout=self.dropout, use_bias=True,kernel_regularizer=L2(0.0005), attention_axes=(1,2))
      self.norm_att = LayerNormalization()
      self.ff_layers =[]
      for i in self.dim_list:
        self.ff_layers.append(Dense(i, use_bias=True, kernel_regularizer=L2(0.001)))
        self.ff_layers.append(LeakyReLU(alpha=0.3))
      self.norm_before_ff = LayerNormalization()
      self.norm_after_ff = LayerNormalization()
      super(Decoder, self).build(input_shape)

    def call(self, inputs, training = None):
      encoder_input, target = inputs
      attention_output_masked = self.masked_multi_attention(query =target, key = target, value = target, training = training, use_causal_mask=True)
      norm_output_masked = self.norm_att(attention_output_masked+target)
      #this is not self, the key and value input are encoder input, query is previous output from norm
      attention_output = self.multi_Attention(query =norm_output_masked, key = encoder_input, value = encoder_input, training = training)
      norm_output = self.norm_before_ff(attention_output+norm_output_masked)
      forward = norm_output
      for ff_layer in self.ff_layers:
        forward = TimeDistributed(ff_layer)(forward)
      forward = self.norm_after_ff(forward+norm_output)
      return forward

    def get_config(self):
      config = super().get_config().copy()
      config.update({
        'dropout': self.dropout,
        'amount_of_heads': self.amount_of_heads,
        'size_of_head': self.size_of_head,
        'output_dim' : self.output_dim,
        'number_ff_layers' : self.number_ff_layers,
        'size_of_head_masked': self.size_of_head_masked,
        'amount_of_heads_masked' : self.amount_of_heads_masked,
      })
      return config

#linear layer
from keras.layers import Dropout

class Linear(Layer):

    def __init__(self, dim_list,  **kwargs):
        super(Linear,self).__init__(**kwargs)
        self.dim_list = dim_list
        self.dense_layers = []

    def build(self, input_shape):
        for i in self.dim_list:
            self.dense_layers.append(Dense(i,activation='linear', kernel_regularizer=L2(0.001)))
        super(Linear, self).build(input_shape)

    def call(self, inputs, training = None):
        forward = inputs
        for layer in self.dense_layers:
            forward = TimeDistributed(layer)(forward)
        return forward

    def get_config(self):
      config = super().get_config().copy()
      config.update({
        'dim_list' : self.dim_list,
        'dense_layers' : [],
      })
      return config

from keras import Model
from keras.layers import Flatten

#constructing the models with all the layers
class Transformer(Model):

    def __init__(self, k=4, encoder_number=4, decoder_number=4, dropout=0.4,amount_of_heads=16,size_of_head=64,batch_size=16, **kwargs): #ff dim must be equal to amount of features to work
        #k=5? because hour, day, week,month, year to identify time? dimension for each thing
        super().__init__(**kwargs)
        self.time2Vec_encoder_eth = Time2Vec(k)
        self.time2Vec_encoder_btc = Time2Vec(k)
        self.time2Vec_decoder = Time2Vec(k)
        self.encoders_eth = []
        self.encoders_btc = []
        self.encoder_eth_btc = []
        self.decoders = []
        self.batch_size = batch_size
        self.dropout = dropout
        for _ in range(encoder_number):
            self.encoders_eth.append(Encoder(dropout,amount_of_heads,size_of_head, output_dim = k+5))
            self.encoders_btc.append(Encoder(dropout,amount_of_heads,size_of_head, output_dim = k+5))
        for _ in range(2):
            self.encoder_eth_btc.append(Encoder(dropout,amount_of_heads,size_of_head, output_dim = k+5))
        for _ in range(decoder_number):
            self.decoders.append(Decoder(dropout = dropout,amount_of_heads= amount_of_heads,size_of_head= size_of_head, output_dim = k+5, dim_list=[36,18,6]))
        self.norm_eth_btc = LayerNormalization()
        self.norm_after_encode_eth_btc = LayerNormalization()
        self.linear_layer = Linear(dim_list= [32,16,1])
        self.flatten = Flatten()

    def call(self, inputs, training=None):
      input_eth, input_btc,input_decoder = inputs
      #first we do the eth part
      time_feature_eth, input_eth = self.splitTimeEmbeddingInputFromData(input_eth)
      time2Vec_eth = self.time2Vec_encoder_eth(time_feature_eth)
      input_encoder_eth = concatenate([time2Vec_eth,input_eth])
      for encode_eth in self.encoders_eth:
        input_encoder_eth = encode_eth(input_encoder_eth, training =training )
      #btc part
      time_feature_btc, input_btc = self.splitTimeEmbeddingInputFromData(input_btc)
      time2Vec_btc =self.time2Vec_encoder_btc(time_feature_btc)
      input_encoder_btc = concatenate([time2Vec_btc,input_btc])
      for encode_btc in self.encoders_btc:
        input_encoder_btc = encode_btc(input_encoder_btc, training =training)
      #concatenate both inputs
      input_from_encoders = self.norm_eth_btc(input_encoder_eth+ input_encoder_btc)
      input_btc_eth =input_from_encoders
      for encoder in self.encoder_eth_btc:
        input_btc_eth=encoder(input_btc_eth, training=training)
      input_btc_eth = self.norm_after_encode_eth_btc(input_btc_eth+input_from_encoders)
      #do the target part (decoder)
      time_feature_decoder, input_decoder = self.splitTimeEmbeddingInputFromData(input_decoder)
      time2vec_decoder =self.time2Vec_decoder(time_feature_decoder)
      input_decoder = concatenate([time2vec_decoder,input_decoder], axis=-1)
      for decoder in self.decoders:
          input_decoder = decoder((input_btc_eth, input_decoder), training =training)
      #flattened_output = self.flatten(input_decoder)
      output = self.linear_layer(input_decoder)
      return output

    def splitTimeEmbeddingInputFromData(self,data):
      time_feature = data[:, :, 0:1]
      rest_of_features = data[:, :, 1:]
      return (time_feature, rest_of_features)

class CustomLearningRateSchedule(tf.keras.optimizers.schedules.LearningRateSchedule):
    def __init__(self, initial_learning_rate=0.005):
        super(CustomLearningRateSchedule, self).__init__()
        self.initial_learning_rate = initial_learning_rate

    def __call__(self, step):
      return self.initial_learning_rate / (1 + 0.05 * step)

class SaveModelH5(tf.keras.callbacks.Callback):
    def on_train_begin(self, logs=None):
         self.val_loss = []
    def on_epoch_end(self, epoch, logs=None):
        current_val_loss = logs.get("val_loss")
        self.val_loss.append(logs.get("val_loss"))
        if current_val_loss <= min(self.val_loss):
            print('Find lowest val_loss. Saving entire model.')
            self.model.save('best_model', save_format='tf') # < ----- Here

from keras.optimizers import Adam

learning_rate = CustomLearningRateSchedule()
batch_size=16
model = Transformer(batch_size=batch_size)
model.compile(loss='mse', optimizer=Adam(learning_rate = learning_rate, epsilon=1e-9, beta_2 = 0.98), metrics='mape')
history = model.fit(complete_data, epochs=25, validation_split=0.1, y=target_eth, verbose=1, batch_size = batch_size)

#prediction on test set

def createTimeEmbeddingsOutputSpecial(batch_size, amount_of_time_embeddings):
  #create time embeddings for the time2vec layer in batches
  target_embeddings = np.linspace(0,1,7)
  target_embeddings = target_embeddings[:amount_of_time_embeddings+1]
  reshape = np.reshape(target_embeddings, (1, len(target_embeddings), 1))
  return np.tile(reshape, (batch_size,1,1))

eth_input, btc_input, decoder_input = complete_test_data
saved_predictions = np.ones((eth_input.shape[0],7,1))
for day_index in range(7):
  #we have a loop of 7 to predict 7 days ahead, each time concatenating the predicted value to the decoder input
  time_vec = createTimeEmbeddingsOutputSpecial(len(decoder_input), day_index)
  decoder_test_timevec = concatenate((time_vec,decoder_input ),axis=-1)
  prediction =  model.predict((eth_input,btc_input,decoder_test_timevec ), batch_size=32)[:,-1,:]
  saved_predictions[:,day_index] = prediction
  prediction = np.reshape(prediction, (prediction.shape[0], prediction.shape[1], 1))
  decoder_input= concatenate((decoder_input,prediction), axis=1)

mape = tf.keras.losses.MeanAbsolutePercentageError()
saved_predictions = np.reshape(saved_predictions,(saved_predictions.shape[0],saved_predictions.shape[1]))
# Compute MAPE
mape_value = mape(target_eth_test, saved_predictions)
print(mape_value)

model.summary()

#wanted plots: ->
# 1) the loss/metrics during training
# 2) the results target vs prediction

import matplotlib.pyplot as plt

training_loss = history.history['loss']
validation_loss = history.history['val_loss']
training_accuracy = history.history['mape']
validation_accuracy = history.history['val_mape']

epochs = range(1, len(training_loss) + 1)

# Creating subplots
plt.figure(figsize=(12, 6))

# Subplot for training and validation loss
plt.subplot(1, 2, 1)  # 1 row, 2 columns, subplot 1
plt.plot(epochs, training_loss, label='Training Loss', color='blue')
plt.plot(epochs, validation_loss, label='Validation Loss', color='green')
plt.title('Training and Validation Loss')
plt.xlabel('Epochs')
plt.ylabel('Loss')
plt.legend()

# Subplot for training and validation accuracy
plt.subplot(1, 2, 2)  # 1 row, 2 columns, subplot 2
plt.plot(epochs, training_accuracy, label='Training MAPE', color='red')
plt.plot(epochs, validation_accuracy, label='Validation MAPE', color='orange')
plt.title('Training and Validation MAPE')
plt.xlabel('Epochs')
plt.ylabel('MAPE')
plt.legend()

from google.colab import files
plt.savefig("loss_metric_progression.png")
files.download("loss_metric_progression.png")

print(target_eth_test.shape, saved_predictions.shape)
mean = eth_daily_scaled_train.mean_[3]
sd = eth_daily_scaled_train.scale_[3]
reverted_target_test =  (target_eth_test*sd)+mean
reverted_prediction_test =  (saved_predictions*sd)+mean

plt.figure(figsize=(16, 10))
plt.subplot(2, 3, 1)  # 10 row, 2 columns, subplot 1
plt.plot(np.arange(1, 8), reverted_target_test[10,:], label='Target value', color='blue')
plt.plot(np.arange(1, 8), reverted_prediction_test[10,:], label='Prediction', color='green')
plt.title('Target vs Prediction')
plt.xlabel('Days')
plt.ylabel('Value')
plt.legend()
plt.subplot(2, 3, 2)  # 1 row, 2 columns, subplot 1
plt.plot(np.arange(1, 8), reverted_target_test[120,:], label='Target value', color='blue')
plt.plot(np.arange(1, 8), reverted_prediction_test[120,:], label='Prediction', color='green')
plt.title('Target vs Prediction')
plt.xlabel('Days')
plt.ylabel('Value')
plt.subplot(2, 3, 3)  # 1 row, 2 columns, subplot 1
plt.plot(np.arange(1, 8), reverted_target_test[80,:], label='Target value', color='blue')
plt.plot(np.arange(1, 8), reverted_prediction_test[80,:], label='Prediction', color='green')
plt.title('Target vs Prediction')
plt.xlabel('Days')
plt.ylabel('Value')
plt.subplot(2, 3, 4)  # 1 row, 2 columns, subplot 1
plt.plot(np.arange(1, 8), reverted_target_test[191,:], label='Target value', color='blue')
plt.plot(np.arange(1, 8), reverted_prediction_test[191,:], label='Prediction', color='green')
plt.title('Target vs Prediction')
plt.xlabel('Days')
plt.ylabel('Value')
plt.subplot(2, 3, 5)  # 1 row, 2 columns, subplot 1
plt.plot(np.arange(1, 8), reverted_target_test[150,:], label='Target value', color='blue')
plt.plot(np.arange(1, 8), reverted_prediction_test[150,:], label='Prediction', color='green')
plt.title('Target vs Prediction')
plt.xlabel('Days')
plt.ylabel('Value')
plt.subplot(2, 3, 6)  # 1 row, 2 columns, subplot 1
plt.plot(np.arange(1, 8), reverted_target_test[40,:], label='Target value', color='blue')
plt.plot(np.arange(1, 8), reverted_prediction_test[40,:], label='Prediction', color='green')
plt.title('Target vs Prediction')
plt.xlabel('Days')
plt.ylabel('Value')
plt.savefig("loss_metric_progression.png")
files.download("loss_metric_progression.png")

#can implement some deep RL method later (like deep q-learning)