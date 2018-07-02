#coding=utf-8

import argparse
import json
import os
import sys
import time
import datetime
from collections import OrderedDict

import cv2
import numpy as np
import urllib

sys.path.insert(0, 'caffe/python')
import caffe

def init_models(weight, deploy, gpu=0):
    """
    initialization caffe model 
        :param gpu: gpu id, 0 by default
        :param weight: weight of caffemodel
        :param deploy: deploy.prototxt
    """
    caffe.set_mode_gpu()
    caffe.set_device(gpu)

    net_cls = caffe.Net(deploy, weight, caffe.TEST)

    return net_cls

# center_crop的具体效果
def center_crop(img, crop_size):
    """
    docstring here
        :param img: 
        :param crop_size: 
    """
    short_edge = min(img.shape[:2])
    if short_edge < crop_size:
        return 
    yy = int((img.shape[0] - crop_size) / 2)
    xx = int((img.shape[1] - crop_size) / 2)
    return img[yy:yy + crop_size, xx: xx + crop_size] 


def label_correspond(label_corres_list, dict_results):
    """
    docstring here
        :param label_corres_list: 
        :param dict_results: 
    """
    label_map = {}   # label的映射map
    for line in label_corres_list:
        ori_label = line.split(' ')[0]
        corres_label = line.split(' ')[1]
        label_map[ori_label] = corres_label

    for (img_name,results) in dict_results.iteritems():
        corres_label = label_map[results['Top-1 Class']]
        dict_results[img_name].update({'Top-1 Class': corres_label})
        dict_results[img_name].update({'Top-1 Index': int(corres_label.split('_')[0])})

        output_prob = results['Confidence']
        corres_prob = []
        corres_prob.append(output_prob[0])
        corres_prob.append(max(float(output_prob[i]) for i in range(1, 5)))
        corres_prob.append(max(float(output_prob[i]) for i in range(5, 7)))
        corres_prob.append(max(float(output_prob[i]) for i in range(7, 9)))
        corres_prob.append(max(float(output_prob[i]) for i in range(9, 11)))
        corres_prob.append(output_prob[11])
        corres_prob.append(output_prob[12])
        corres_prob.append(output_prob[13])
        corres_prob.append(output_prob[14])
        corres_prob.append(output_prob[15])
        corres_prob.append(output_prob[16])
        corres_prob.append(output_prob[17])
        corres_prob.append(max(float(output_prob[i]) for i in range(18, 48)))

        dict_results[img_name].update({'Confidence': [str(i) for i in list(corres_prob)]})
    return dict_results


def single_img_process(net_cls, img, label_list):
    """
    docstring here
        :param net_cls: 
        :param img_path: 
        :param ori_img: 
        :param label_list: 
    """
    #img = cv2.imread(os.path.join(img_path, ori_img))
    if np.shape(img) != () and np.shape(img)[2] != 4:
        start_time = time.time()
        img = img.astype(np.float32, copy=True)
        img = cv2.resize(img, (256, 256))
        # img = img.astype(np.float32, copy=True)
        img -= np.array([[[103.94, 116.78, 123.68]]])
        img = img * 0.017

        img = center_crop(img, 225)
        
        img = img.transpose((2, 0, 1))
        end_time = time.time()
        print('Image preprocess speed: {:.3f}s / iter'.format(end_time - start_time))

        net_cls.blobs['data'].data[...] = img
        output = net_cls.forward()
        output_prob = np.squeeze(output['prob'][0])

        index_list = output_prob.argsort()
        rate_list = output_prob[index_list]

        result_dict = OrderedDict()
        result_dict['Top-1 Index'] = index_list[-1]
        result_dict['Top-1 Class'] = label_list[int(index_list[-1])].split(' ')[1]

        result_dict['Confidence'] = [str(i) for i in list(output_prob)]
        return result_dict
    print '*'*40 + ' Error image ' + '*'*40 
    return None


def generate_rg_results(dict_results, threshold, output):
    """
    docstring here
        :param dict_results: 
        :param threshold: 
        :param output: 
    """
    # 回归测试48类到6类的类别映射表
    labels = ['bloodiness', 'bomb', 'beheaded', 'march', 'fight', 'normal']
    map = {'0': [0],  # 'bloodiness'
           '1': [1, 2, 3, 4],  # 'bomb'
           '2': [5, 6],  # 'beheaded'
           '3': [7, 8],  # 'march' 
           '4': [9, 10],  # 'fight'
           '5': list(range(11, 48))}  # 'normal'

    with open(output, 'w') as fo:
        for (img_name, results) in dict_results.iteritems():
            label = OrderedDict()
            img_name = os.path.split(img_name)[-1]
            index = int(results['Top-1 Index'])
            prob = float(results['Confidence'][index])
            # 获取对应的label
            [cls_name] = [labels[int(key)] for key in map.keys() if index in map[key]]
            # 暴恐分类目前的线上逻辑: 只有类别是非normal，并且score小于0.9的才被标为reviewer
            if prob < threshold and cls_name != 'normal':
                cls_name = 'normal'
                index = -1

            label["class"] = cls_name
            label["index"] = index
            label["score"] = prob

            fo.write(img_name + '\t')
            json.dump(label, fo)
            fo.write('\n')
            
    print "Generate %s with success" % (output)


def process_single_img(img_path, net_cls, label_list):
    dict_results = OrderedDict()
    start_time = time.time()
    img = cv2.imread(img_path)
    dict_result = single_img_process(net_cls, img, label_list)
    end_time = time.time()
    print('Inference speed: {:.3f}s / iter'.format(end_time - start_time))
    dict_result.update({'File Name': img_path})
    dict_results[os.path.basename(img_path)] = dict_result
    return dict_results


def process_img_list(root, img_list_path, net_cls, label_list):
    img_list = np.loadtxt(img_list_path, str, delimiter='\n')
    dict_results = OrderedDict()
    for i in range(len(img_list)):
        start_time = time.time()
        img_path = os.path.join(root, img_list[i].split(' ')[0])
        img = cv2.imread(img_path)
        dict_result = single_img_process(net_cls, img, label_list)
        end_time = time.time()
        print('Inference speed: {:.3f}s / iter'.format(end_time - start_time))
        dict_result.update({'File Name': img_path})
        dict_results[os.path.basename(img_path)] = dict_result
    return dict_results


def process_img_urllist(url_list_path, prefix, net_cls, label_list):
    url_list = np.loadtxt(url_list_path, str, delimiter='\n')
    dict_results = OrderedDict()
    for i in range(len(url_list)):
        url = prefix + url_list[i] if prefix else url_list[i]
        start_time = time.time()
        img = urllib.urlopen(url).read()
        img = np.fromstring(img, np.uint8)
        img = cv2.imread(img, 1)
        dict_result = single_img_process(net_cls, img, label_list)
        end_time = time.time()
        print('Inference speed: {:.3f}s / iter'.format(end_time - start_time))
        dict_result.update({'File Name': url})
        dict_results[os.path.basename(url)] = dict_result
    return dict_results

def parse_arg():
    parser = argparse.ArgumentParser(description='caffe image classify')
    parser.add_argument('--weight', help='caffemodel', type=str, required=True)
    parser.add_argument('--deploy', help='deploy.prototxt',type=str, required=True)
    parser.add_argument('--gpu', help='gpu id', type=int, required=True)
    parser.add_argument('--labels', help='labels list',type=str, required=True)
    parser.add_argument('-thrs','--threshold', help='threshold for inference result',type=float, default=0.9)
    parser.add_argument('--labels_corres', help='labels correspond list', type=str, required=False)
    parser.add_argument('-rg','--regression_result', help='add "--rg" to generate regression result',action='store_true')
    parser.add_argument('--img', help='input image, inference for single local image', type=str, required=False)
    parser.add_argument('--img_list', help='input image list', default=None, type=str, required=False)
    parser.add_argument('--root', help='data root for image', default=None, type=str, required=False)
    parser.add_argument('--url_list', help='input image url list', default=None, type=str, required=False)
    parser.add_argument('--prefix', help='prefix for image url', default=None, type=str, required=False)
    
    return parser.parse_args()

def main():
    args = parse_arg()
    now = datetime.datetime.now()
    
    net_cls = init_models(args.weight, args.deploy, args.gpu)
    label_list = np.loadtxt(args.labels, str, delimiter='\n')

    dict_results = OrderedDict()
    if args.img:
        # 推理单张图片
        dict_results = process_single_img(args.img, net_cls, label_list)
    elif args.img_list:
        # 推理存储在本地的图片
        dict_results = process_img_list(
            args.root, args.img_list, net_cls, label_list)
    elif args.url_list:
        # 推理url形式的图片
        dict_results = process_img_urllist(
            args.url_list, args.prefix, net_cls, label_list)
    
    if args.regression_result:
        rg_output = os.path.join(args.root, 'regression_%s.tsv' % (now.strftime("%m%d%H%M")))
        generate_rg_results(dict_results, args.threshold, rg_output)
            
    if args.labels_corres:
        label_corres_list = np.loadtxt(args.labels_corres, str, delimiter='\n')
        dict_results = label_correspond(label_corres_list, dict_results)

    output = os.path.join(args.root, 'results_%s.json' % (now.strftime("%m%d%H%M")))
    
    with open(output, 'w') as f:
        json.dump(dict_results, f, indent=4)
    print "Generate %s with success" % (output)

if __name__ == '__main__':
    print('Start caffe image classify:')
    main()
    print('End process.')
