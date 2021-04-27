'''
Network class "MK11" for the neural entropy closure.
MK7 ICNN with sobolev wrapper.
Author: Steffen Schotthöfer
Version: 0.0
Date 09.04.2020
'''
from .neuralBase import neuralBase
from .neuralBase import LossAndErrorPrintingCallback

import numpy as np
import tensorflow as tf
from tensorflow import keras as keras
from tensorflow.keras import layers
from tensorflow.keras.constraints import NonNeg
from tensorflow import Tensor
from src import math


class neuralMK11(neuralBase):
    '''
    MK4 Model: Train u to h and alpha
    Training data generation: b) read solver data from file: Uses C++ Data generator
    Loss function:  MSE between h_pred and real_h
    '''

    def __init__(self, polyDegree=0, spatialDim=1, folderName="testFolder", optimizer='adam', width=10, depth=5,
                 normalized=False):
        if (folderName == "testFolder"):
            customFolderName = "MK11_N" + str(polyDegree) + "_D" + str(spatialDim)
        else:
            customFolderName = folderName

        super(neuralMK11, self).__init__(normalized, polyDegree, spatialDim, width, depth, optimizer,
                                         customFolderName)

        self.model = self.createModel()

    def createModel(self):

        layerDim = self.modelWidth

        # Weight initializer
        # 1. This is a modified Kaiming inititalization with a first-order taylor expansion of the
        # softplus activation function (see S. Kumar "On Weight Initialization in
        # Deep Neural Networks").

        # Extra factor of (1/1.1) added inside sqrt to suppress inf for 1 dimensional inputs
        input_stddev = np.sqrt((1 / 1.1) * (1 / self.inputDim) * (1 / ((1 / 2) ** 2)) * (1 / (1 + np.log(2) ** 2)))
        hidden_stddev = np.sqrt((1 / 1.1) * (1 / self.modelWidth) * (1 / ((1 / 2) ** 2)) * (1 / (1 + np.log(2) ** 2)))

        # Weight regularizer
        l1l2Regularizer = tf.keras.regularizers.L1L2(l1=0.00001, l2=0.00001)  # L1 + L2 penalties

        def convexLayer(layerInput_z: Tensor, netInput_x: Tensor, layerIdx=0) -> Tensor:
            # Weighted sum of previous layers output plus bias
            weightedNonNegSum_z = layers.Dense(layerDim, kernel_constraint=NonNeg(), activation=None,
                                               kernel_initializer=keras.initializers.RandomNormal(mean=0.,
                                                                                                  stddev=hidden_stddev),
                                               kernel_regularizer=l1l2Regularizer,
                                               use_bias=True, bias_initializer='zeros',
                                               name='non_neg_component_' + str(layerIdx)
                                               )(layerInput_z)
            # Weighted sum of network input
            weightedSum_x = layers.Dense(layerDim, activation=None,
                                         kernel_initializer=keras.initializers.RandomNormal(mean=0.,
                                                                                            stddev=hidden_stddev),
                                         kernel_regularizer=l1l2Regularizer,
                                         use_bias=False, name='dense_component_' + str(layerIdx)
                                         )(netInput_x)
            # Wz+Wx+b
            intermediateSum = layers.Add(name='add_component_' + str(layerIdx))([weightedSum_x, weightedNonNegSum_z])

            # activation
            out = tf.keras.activations.softplus(intermediateSum)
            # batch normalization
            # out = layers.BatchNormalization(name='bn_' + str(layerIdx))(out)
            return out

        def convexLayerOutput(layerInput_z: Tensor, netInput_x: Tensor) -> Tensor:
            # Weighted sum of previous layers output plus bias
            weightedNonNegSum_z = layers.Dense(1, kernel_constraint=NonNeg(), activation=None,
                                               kernel_initializer=keras.initializers.RandomNormal(mean=0.,
                                                                                                  stddev=hidden_stddev),
                                               kernel_regularizer=l1l2Regularizer,
                                               use_bias=True,
                                               bias_initializer='zeros'
                                               # name='in_z_NN_Dense'
                                               )(layerInput_z)
            # Weighted sum of network input
            weightedSum_x = layers.Dense(1, activation=None,
                                         kernel_initializer=keras.initializers.RandomNormal(mean=0.,
                                                                                            stddev=hidden_stddev),
                                         kernel_regularizer=l1l2Regularizer,
                                         use_bias=False
                                         # name='in_x_Dense'
                                         )(netInput_x)
            # Wz+Wx+b
            intermediateSum = layers.Add()([weightedSum_x, weightedNonNegSum_z])

            # activation
            # out = tf.keras.activations.softplus(intermediateSum)
            # batch normalization
            # out = layers.BatchNormalization()(out)
            return intermediateSum

        ### build the core network with icnn closure architecture ###
        input_ = keras.Input(shape=(self.inputDim,))
        # First Layer is a std dense layer
        hidden = layers.Dense(layerDim, activation="softplus",
                              kernel_initializer=keras.initializers.RandomNormal(mean=0., stddev=input_stddev),
                              kernel_regularizer=l1l2Regularizer,
                              bias_initializer='zeros',
                              name="first_dense"
                              )(input_)
        # other layers are convexLayers
        for idx in range(0, self.modelDepth):
            hidden = convexLayer(hidden, input_, layerIdx=idx)
        output_ = convexLayerOutput(hidden, input_)  # outputlayer

        # Create the core model
        coreModel = keras.Model(inputs=[input_], outputs=[output_], name="Icnn_closure")

        # build model
        model = sobolevModel(coreModel, polyDegree=self.polyDegree, name="sobolev_icnn_wrapper")

        batchSize = 2  # dummy entry
        model.build(input_shape=(batchSize, self.inputDim))

        model.compile(
            loss={'output_1': tf.keras.losses.MeanSquaredError(), 'output_2': tf.keras.losses.MeanSquaredError()},
            loss_weights={'output_1': 1, 'output_2': 1},
            optimizer='adam',
            metrics=['mean_absolute_error'])

        # model.summary()

        # tf.keras.utils.plot_model(model, to_file=self.filename + '/modelOverview', show_shapes=True,
        # show_layer_names = True, rankdir = 'TB', expand_nested = True)

        return model

    def trainModel(self, valSplit=0.1, epochCount=2, epochChunks=1, batchSize=500, verbosity=1, processingMode=0):
        '''
        Method to train network
        '''

        # Create callbacks
        mc_best = tf.keras.callbacks.ModelCheckpoint(self.filename + '/best_model.h5', monitor='loss', mode='min',
                                                     save_best_only=True,
                                                     verbose=verbosity)  # , save_weights_only = True, save_freq = 50, verbose=0)

        es = tf.keras.callbacks.EarlyStopping(monitor='loss', mode='min', min_delta=0.000001, patience=100,
                                              verbose=1)
        # mc_checkpoint =  tf.keras.callbacks.ModelCheckpoint(filepath=self.filename + '/model_saved',
        #                                         save_weights_only=False,
        #                                         verbose=1)

        # Split Training epochs
        miniEpoch = int(epochCount / epochChunks)

        for i in range(0, epochChunks):
            #  perform a batch doublication every 1/10th of the epoch count
            print("Current Batch Size: " + str(batchSize))

            # assemble callbacks
            callbackList = []
            csv_logger = self.createCSVLoggerCallback()

            if verbosity == 1:
                callbackList = [mc_best, es, csv_logger]
            else:
                callbackList = [mc_best, es, LossAndErrorPrintingCallback(), csv_logger]

            # start Training
            h = self.trainingData[2]
            alpha = self.trainingData[1]
            # u = self.trainingData[0]
            # trainDataY =          net_out = tf.stack([h, alpha], axis=1)[:, :, 0]

            # self.history = self.model.fit(x=self.trainingData[0], y=self.trainingData[2],
            self.history = self.model.fit(x=self.trainingData[0], y=[self.trainingData[2], self.trainingData[1]],
                                          validation_split=valSplit,
                                          epochs=miniEpoch,
                                          batch_size=batchSize,
                                          verbose=verbosity,
                                          callbacks=callbackList,
                                          shuffle=True
                                          )
            batchSize = 2 * batchSize

            self.concatHistoryFiles()

        return self.history

    def selectTrainingData(self):
        return [True, True, True]

    def trainingDataPostprocessing(self):
        return 0

    def callNetwork(self, u_complete):
        """
        brief: Only works for maxwell Boltzmann entropy so far.
        nS = batchSize
        N = basisSize
        nq = number of quadPts

        input: u_complete, dims = (nS x N)
        returns: alpha_complete_predicted, dim = (nS x N)
                 u_complete_reconstructed, dim = (nS x N)
                 h_predicted, dim = (nS x 1)
        """
        u_reduced = u_complete[:, 1:]  # chop of u_0
        [h_predicted, alpha_predicted] = self.model(u_reduced)
        alpha_complete_predicted = self.model.reconstruct_alpha(alpha_predicted)
        u_complete_reconstructed = self.model.reconstruct_u(alpha_complete_predicted)

        return [u_complete_reconstructed, alpha_complete_predicted, h_predicted]


class sobolevModel(tf.keras.Model):
    # Sobolev implies, that the model outputs also its derivative
    def __init__(self, coreModel, polyDegree=1, **opts):
        super(sobolevModel, self).__init__()
        # Member is only the model we want to wrap with sobolev execution
        self.coreModel = coreModel  # must be a compiled tensorflow model

        # Create quadrature and momentBasis. Currently only for 1D problems
        self.polyDegree = polyDegree
        self.nq = 100
        [quadPts, quadWeights] = math.qGaussLegendre1D(self.nq)  # dims = nq
        self.quadPts = tf.constant(quadPts, shape=(1, self.nq), dtype=tf.float32)  # dims = (batchSIze x N x nq)
        self.quadWeights = tf.constant(quadWeights, shape=(1, self.nq),
                                       dtype=tf.float32)  # dims = (batchSIze x N x nq)
        mBasis = math.computeMonomialBasis1D(quadPts, self.polyDegree)  # dims = (N x nq)
        self.inputDim = mBasis.shape[0]
        self.momentBasis = tf.constant(mBasis, shape=(self.inputDim, self.nq),
                                       dtype=tf.float32)  # dims = (batchSIze x N x nq)

    def call(self, x, training=False):
        """
        Defines the sobolev execution
        """

        with tf.GradientTape() as grad_tape:
            grad_tape.watch(x)
            h = self.coreModel(x)
        alpha = grad_tape.gradient(h, x)

        return [h, alpha]

    def callDerivative(self, x, training=False):
        with tf.GradientTape() as grad_tape:
            grad_tape.watch(x)
            y = self.coreModel(x)
        derivativeNet = grad_tape.gradient(y, x)

        return derivativeNet

    def reconstruct_alpha(self, alpha):
        """
        brief:  Reconstructs alpha_0 and then concats alpha_0 to alpha_1,... , from alpha1,...
                Only works for maxwell Boltzmann entropy so far.
        nS = batchSize
        N = basisSize
        nq = number of quadPts

        input: alpha, dims = (nS x N-1)
               m    , dims = (N x nq)
               w    , dims = nq
        returns alpha_complete = [alpha_0,alpha], dim = (nS x N), where alpha_0 = - ln(<exp(alpha*m)>)
        """
        tmp = tf.math.exp(tf.tensordot(alpha, self.momentBasis[1:, :], axes=([1], [0])))  # tmp = alpha * m
        alpha_0 = -tf.math.log(tf.tensordot(tmp, self.quadWeights, axes=([1], [1])))  # ln(<tmp>)
        return tf.concat([alpha_0, alpha], axis=1)  # concat [alpha_0,alpha]

    def reconstruct_u(self, alpha):
        """
        brief: reconstructs u from alpha
        nS = batchSize
        N = basisSize
        nq = number of quadPts

        input: alpha, dims = (nS x N)
               m    , dims = (N x nq)
               w    , dims = nq
        returns u = <m*eta_*'(alpha*m)>, dim = (nS x N)
        """
        # Currently only for maxwell Boltzmann entropy
        f_quad = tf.math.exp(tf.tensordot(alpha, self.momentBasis, axes=([1], [0])))  # alpha*m
        tmp = tf.math.multiply(f_quad, self.quadWeights)  # f*w
        return tf.tensordot(tmp, self.momentBasis[:, :], axes=([1], [1]))  # f * w * momentBasis